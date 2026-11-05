import logging
import numpy as np
from datetime import datetime, timedelta
from db import db
from database import User, Transaction, UserBehaviorBaseline, TrustedPayee, ScamUpi
from geofence import check_geofence, check_impossible_travel
from social_graph import global_txn_graph
from qr_parser import parse_upi_qr, validate_qr
from website_trust import WebsiteTrustScore
from predictor import predict_fraud_ensemble
from learned_fusion import get_fusion_prediction

logger = logging.getLogger(__name__)

# Configurable hard-override rules table applied post-scoring
OVERRIDE_RULES = [
    {
        "id": "RULE_SCAM_BLACKLIST",
        "name": "Payee in scam blacklist",
        "min_score": 90.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "Payee in scam blacklist -> BLOCKED (at least 90)",
        "reason": "Payee in scam blacklist (hard override: BLOCKED, min score 90)"
    },
    {
        "id": "RULE_QR_PAYEE_MISMATCH",
        "name": "QR payee mismatch",
        "min_score": 85.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "QR payee mismatch -> BLOCKED (at least 85)",
        "reason": "QR payee mismatch detected (hard override: BLOCKED, min score 85)"
    },
    {
        "id": "RULE_IMPOSSIBLE_TRAVEL_NEW_DEVICE",
        "name": "Impossible travel and new device",
        "min_score": 85.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "Impossible travel AND new device -> BLOCKED (at least 85)",
        "reason": "Impossible travel from an unrecognized device (hard override: BLOCKED, min score 85)"
    },
    {
        "id": "RULE_MALICIOUS_DOMAIN",
        "name": "Website flagged by Safe Browsing or OpenPhish",
        "min_score": 85.0,
        "forced_status": "BLOCKED",
        "enabled": True,
        "description": "Website flagged by Safe Browsing or OpenPhish -> BLOCKED (at least 85)",
        "reason": "Website flagged by Safe Browsing or OpenPhish (hard override: BLOCKED, min score 85)"
    },
    {
        "id": "RULE_MULE_TOPOLOGY",
        "name": "Mule-topology receiver",
        "min_score": 70.0,
        "forced_status": None,
        "enabled": True,
        "description": "Mule-topology receiver -> at least 70",
        "reason": "Mule-topology receiver detected (hard override: min score 70)"
    },
    {
        "id": "RULE_NEW_DEVICE_NEW_PAYEE_HIGH_AMOUNT",
        "name": "New device AND new payee AND amount over 5x average",
        "min_score": 70.0,
        "forced_status": None,
        "enabled": True,
        "description": "New device AND new payee AND amount over 5x average -> at least 70",
        "reason": "High amount (>5x average) to new payee from new device (hard override: min score 70)"
    },
    {
        "id": "RULE_EXTREME_AMOUNT_NEW_PAYEE",
        "name": "Amount over 10x average AND new payee",
        "min_score": 70.0,
        "forced_status": None,
        "enabled": True,
        "description": "Amount over 10x average AND new payee -> at least 70",
        "reason": "Extreme amount (>10x average) to new payee (hard override: min score 70)"
    },
    {
        "id": "RULE_NEW_PAYEE_COOLING_CAP",
        "name": "Amount over Rs 5,000 to a payee added less than 24 hours ago",
        "min_score": 70.0,
        "forced_status": None,
        "enabled": True,
        "description": "Amount over Rs 5,000 to a payee added less than 24 hours ago -> at least 70",
        "reason": "Amount over Rs 5,000 to payee added < 24 hours ago (hard override: min score 70)"
    }
]


def evaluate_overrides(layer_scores: dict, features: dict, context: dict, weighted_score: float) -> tuple:
    """
    Evaluates configurable hard-override rules post-weighted-scoring.
    
    Args:
        layer_scores: dict of scores across the 7 layers
        features: dict of 22 engineered features
        context: dict containing contextual flags (is_scam, qr_mismatch, etc.)
        weighted_score: the aggregated weighted score before hard overrides
        
    Returns:
        tuple of (final_score: float, override_applied: bool, override_reasons: list[str])
    """
    rules_by_id = {r['id']: r for r in OVERRIDE_RULES if r.get('enabled', True)}
    override_reasons = []
    max_score = weighted_score

    # Rule 1: Payee in scam blacklist -> BLOCKED (at least 90)
    rule = rules_by_id.get('RULE_SCAM_BLACKLIST')
    if rule and (context.get('is_scam') or context.get('is_scam_flag')):
        max_score = max(max_score, rule['min_score'])
        override_reasons.append(rule['reason'])

    # Rule 2: QR payee mismatch -> BLOCKED (at least 85)
    rule = rules_by_id.get('RULE_QR_PAYEE_MISMATCH')
    if rule and (context.get('qr_mismatch') or context.get('qr_payee_mismatch')):
        max_score = max(max_score, rule['min_score'])
        override_reasons.append(rule['reason'])

    # Rule 3: Impossible travel AND new device -> BLOCKED (at least 85)
    rule = rules_by_id.get('RULE_IMPOSSIBLE_TRAVEL_NEW_DEVICE')
    if rule and context.get('is_impossible_travel') and context.get('is_new_device'):
        max_score = max(max_score, rule['min_score'])
        override_reasons.append(rule['reason'])

    # Rule 4: Website flagged by Safe Browsing or OpenPhish -> BLOCKED (at least 85)
    rule = rules_by_id.get('RULE_MALICIOUS_DOMAIN')
    if rule and (context.get('website_flagged') or context.get('is_phishing_domain')):
        max_score = max(max_score, rule['min_score'])
        override_reasons.append(rule['reason'])

    # Rule 5: Mule-topology receiver -> at least 70
    rule = rules_by_id.get('RULE_MULE_TOPOLOGY')
    if rule and (context.get('is_mule') or context.get('is_mule_candidate')):
        max_score = max(max_score, rule['min_score'])
        override_reasons.append(rule['reason'])

    # Rule 6: New device AND new payee AND amount over 5x average -> at least 70
    rule = rules_by_id.get('RULE_NEW_DEVICE_NEW_PAYEE_HIGH_AMOUNT')
    if rule and context.get('is_new_device') and context.get('is_new_payee') and context.get('amount_over_5x_avg'):
        max_score = max(max_score, rule['min_score'])
        override_reasons.append(rule['reason'])

    # Rule 7: Amount over 10x average AND new payee -> at least 70
    rule = rules_by_id.get('RULE_EXTREME_AMOUNT_NEW_PAYEE')
    if rule and context.get('amount_over_10x_avg') and context.get('is_new_payee'):
        max_score = max(max_score, rule['min_score'])
        override_reasons.append(rule['reason'])

    # Rule 8: Amount over Rs 5,000 to a payee added less than 24 hours ago -> at least 70
    rule = rules_by_id.get('RULE_NEW_PAYEE_COOLING_CAP')
    if rule:
        is_cooling_cap_hit = context.get('payee_added_under_24h_amount_over_5k') or (
            float(context.get('amount', 0.0)) > 5000.0 and context.get('payee_added_under_24h')
        )
        if is_cooling_cap_hit:
            max_score = max(max_score, rule['min_score'])
            override_reasons.append(rule['reason'])

    override_applied = len(override_reasons) > 0
    final_score = float(np.clip(max_score, 0.0, 100.0))
    return final_score, override_applied, override_reasons


class FraudDetectionEngine:
    def __init__(self):
        self.wts = WebsiteTrustScore()

    def detect(self, txn_data: dict) -> dict:
        """
        Runs the 7-layer fraud detection engine.
        txn_data schema:
            {
                'user_id': str,
                'sender_upi': str,
                'receiver_upi': str,
                'amount': float,
                'device_id': str,
                'latitude': float,
                'longitude': float,
                'biometric_failed': bool,
                'qr_code': str (optional),
                'mcc_code': str (optional)
            }
        Returns:
            Dictionary containing final risk score, status, layer scores, and warning flags.
        """
        user_id = txn_data['user_id']
        sender_upi = txn_data['sender_upi']
        receiver_upi = txn_data['receiver_upi']
        amount = float(txn_data['amount'])
        device_id = txn_data['device_id']
        latitude = float(txn_data.get('latitude', txn_data.get('lat', 0.0)))
        longitude = float(txn_data.get('longitude', txn_data.get('lon', 0.0)))
        biometric_failed = txn_data.get('biometric_failed', False)
        qr_code = txn_data.get('qr_code', '')
        mcc_code = txn_data.get('mcc_code', '0000') # 0000 is default merchant category

        now = datetime.utcnow()
        hour = now.hour
        day_of_week = now.weekday()

        # Fetch baseline
        baseline = UserBehaviorBaseline.query.filter_by(user_id=user_id).first()
        
        # Check if payee is in trusted payee list (3+ successful txns)
        trusted = TrustedPayee.query.filter_by(user_id=user_id, payee_upi=receiver_upi).first()
        is_trusted = trusted is not None and trusted.txn_count >= 3

        flags = []
        layer_scores = {}

        # ====================================================
        # RUN ML MODELS ENSEMBLE FOR BEHAVIOR & AMOUNT INPUTS
        # ====================================================
        # We engineer standard inputs to feed into predictor.py
        # Prepare the features dict matching FEATURE_COLS
        avg_amt = float(baseline.avg_amount) if baseline and baseline.avg_amount else 1000.0
        std_amt = float(baseline.std_amount) if baseline and baseline.std_amount else 100.0
        
        z_score = (amount - avg_amt) / std_amt if std_amt > 0 else 0.0
        avg_ratio = amount / avg_amt if avg_amt > 0 else 1.0
        
        # Check if geofence warns (with accuracy_m threshold)
        geo_score, geo_warns = check_geofence(user_id, latitude, longitude, accuracy_m=txn_data.get('accuracy_m'))
        travel_score, _ = check_impossible_travel(user_id, latitude, longitude, now)
        
        # Check if scam UPI
        scam_record = ScamUpi.query.filter_by(upi_id=receiver_upi).first()
        is_scam_flag = 1 if scam_record else 0
        
        # Mule candidate check
        is_mule, _ = global_txn_graph.is_mule_candidate(receiver_upi)
        centrality = global_txn_graph.get_centrality_score(receiver_upi)

        # High risk MCC check (e.g. gambling/crypto: 7995, 6051, 4829)
        is_high_risk_mcc = 1.0 if mcc_code in ['7995', '6051', '4829'] else 0.0

        # Construct canonical 22 features strictly using feature_builder
        from feature_builder import build_feature_vector
        engineered_features = build_feature_vector(
            txn={
                'amount': amount,
                'now': now,
                'hour': hour,
                'day_of_week': day_of_week,
                'receiver_upi': receiver_upi,
                'device_id': device_id,
                'mcc_code': mcc_code,
                'is_high_risk_mcc': is_high_risk_mcc
            },
            baseline=baseline,
            graph={
                'payee_graph_centrality': centrality,
                'is_mule_candidate': 1.0 if is_mule else 0.0
            },
            device_state={
                'device_id': device_id,
                'known_device_flag': 1.0 if (baseline and device_id in (baseline.known_devices or [])) else 0.0,
                'device_change_count_30days': len(baseline.known_devices) if baseline else 1.0
            },
            geo_state={
                'distance_from_home_km': 10.0,
                'is_impossible_travel': 1.0 if travel_score > 0 else 0.0
            },
            payee_state={
                'is_scam_upi': float(is_scam_flag),
                'payee_incoming_txn_count': 10.0,
                'payee_account_age_days': 150.0,
                'new_payee_flag': 0.0 if (baseline and receiver_upi in (baseline.known_payees or [])) else 1.0,
                'new_payee_pct_last_7days': 0.1
            }
        )

        # Velocity checks
        ten_min_ago = now - timedelta(minutes=10)
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=24)
        
        txn_count_10m = Transaction.query.filter_by(user_id=user_id).filter(Transaction.created_at >= ten_min_ago).count()
        txn_count_1h = Transaction.query.filter_by(user_id=user_id).filter(Transaction.created_at >= one_hour_ago).count()
        txn_count_24h = Transaction.query.filter_by(user_id=user_id).filter(Transaction.created_at >= one_day_ago).count()

        # Run model ensemble predict
        ensemble_prob, ensemble_conf, model_probs = predict_fraud_ensemble(engineered_features, user_id)

        # ====================================================
        # LAYER 1 — Behavioral (38% Weight)
        # ====================================================
        # Base: ensemble model probability provides the core behavior score
        layer1_score = ensemble_prob * 100.0
        
        # Add heuristics - cap Z-score bonus at 60 points (Part 23)
        if z_score > 3.0:
            layer1_score += 60.0
            flags.append(f"Z-Score amount deviation warning: z-score is {z_score:.2f} (exceeds limit 3.0, bonus capped at 60 points)")

        if txn_count_10m > 3:
            layer1_score += 40.0
            flags.append(f"High velocity burst detected: {txn_count_10m} transactions in last 10 minutes")

        if hour >= 0 and hour <= 5:
            layer1_score += 15
            flags.append("Night transaction (between 12 AM and 5 AM)")
            
        if not baseline or baseline.txn_count == 0:
            layer1_score += 10
            flags.append("First transaction ever on this account")
            
        if day_of_week >= 5 and amount > 10000.0:
            layer1_score += 20
            flags.append("Large amount transaction during weekend")
            
        layer_scores['behavioral'] = float(min(layer1_score, 100.0))

        # ====================================================
        # LAYER 2 — Velocity (4% Weight)
        # ====================================================
        layer2_score = 0
        if txn_count_10m > 3:
            layer2_score += 80
            flags.append(f"High velocity: {txn_count_10m} transactions in last 10 minutes")
        if txn_count_1h > 10:
            layer2_score += 60
            flags.append(f"High velocity: {txn_count_1h} transactions in last hour")
        if txn_count_24h > 30:
            layer2_score += 80
            flags.append(f"High velocity: {txn_count_24h} transactions in last 24 hours")
            
        layer_scores['velocity'] = float(min(layer2_score, 100.0))

        # ====================================================
        # LAYER 3 — Flow (3% Weight)
        # ====================================================
        layer3_score = 0
        is_mule, mule_val = global_txn_graph.is_mule_candidate(receiver_upi)
        if is_mule:
            layer3_score += mule_val
            flags.append(f"Mule candidate flag: receiver node matches flow anomalies ({receiver_upi})")
            
        # Check chain transfer: query recent incoming vs outgoing to check if receiver transfers out 90%+
        # For simulation, check graph degree flow
        if receiver_upi in global_txn_graph.graph:
            in_weight = sum(d.get('weight', 0) for _, _, d in global_txn_graph.graph.in_edges(receiver_upi, data=True))
            out_weight = sum(d.get('weight', 0) for _, _, d in global_txn_graph.graph.out_edges(receiver_upi, data=True))
            if in_weight > 1000 and out_weight >= 0.9 * in_weight:
                layer3_score += 60
                flags.append("Chain transfer: Receiver routes >90% of incoming funds immediately")
                
        layer_scores['flow'] = float(min(layer3_score, 100.0))

        # ====================================================
        # LAYER 4 — Payee (28% Weight)
        # ====================================================
        layer4_score = 0
        
        # 1. Scam UPI blacklist check (refresh every 6h/always queries DB)
        if is_scam_flag:
            layer4_score += 100
            flags.append(f"Receiver UPI is blacklisted as scam: {receiver_upi}")
            
        # 2. Receiver UPI registered < 7 days check
        is_new_payee = not (baseline and baseline.known_payees and receiver_upi in baseline.known_payees)
        if is_new_payee:
            # Check if receiver is a registered user
            # Registered payees are found via the blind upi/phone hash (user_id != phone digits).
            from user_manager import find_user_by_upi_or_phone
            receiver_user = find_user_by_upi_or_phone(receiver_upi)
            if receiver_user:
                age_days = (now - receiver_user.created_at).days
                if age_days < 7:
                    layer4_score += 40
                    flags.append(f"Receiver UPI is recently registered (< 7 days): {receiver_upi}")
            else:
                # receiver_upi is Fernet-encrypted (non-deterministic): match by decrypting
                # recent rows instead of comparing a fresh ciphertext (which never matched).
                from security import decrypt_val
                first_txn = None
                for t in Transaction.query.order_by(Transaction.created_at.asc()).limit(5000):
                    if decrypt_val(t.receiver_upi) == receiver_upi:
                        first_txn = t
                        break
                if not first_txn:
                    layer4_score += 40
                    flags.append(f"Receiver UPI is new to the system (< 7 days): {receiver_upi}")
                else:
                    first_seen_days = (now - first_txn.created_at).days
                    if first_seen_days < 7:
                        layer4_score += 40
                        flags.append(f"Receiver UPI first seen recently (< 7 days): {receiver_upi}")

        # 3. UPI format bank suffix check
        # Standard bank suffixes: @okaxis, @okhdfc, @okicici, @paytm, @ybl, @axl, @ibl, @sbi, @barodampay
        # '@mlbfd' is the platform's own handle: every allowed payee is a registered @mlbfd user.
        valid_suffixes = ['@mlbfd', '@okaxis', '@okhdfc', '@okicici', '@paytm', '@ybl', '@axl', '@ibl', '@sbi', '@barodampay']
        suffix_match = False
        for suffix in valid_suffixes:
            if receiver_upi.lower().endswith(suffix):
                suffix_match = True
                break
        if not suffix_match:
            layer4_score += 20
            flags.append("Suspicious bank suffix in receiver UPI ID")
            
        # 4. QR Tampering checks
        qr_mismatch = False
        if qr_code:
            qr_data = parse_upi_qr(qr_code)
            qr_score, qr_flags = validate_qr(qr_data, receiver_upi, amount)
            layer4_score += qr_score
            flags.extend(qr_flags)
            if qr_data.get('pa') and qr_data['pa'].strip().lower() != receiver_upi.strip().lower():
                qr_mismatch = True
            
        layer_scores['payee'] = float(min(layer4_score, 100.0))

        # ====================================================
        # LAYER 5 — Compromise (15% Weight)
        # ====================================================
        layer5_score = 0
        
        # Device Check
        known_devices = list(baseline.known_devices or []) if baseline else []
        if device_id not in known_devices:
            # Bug fix 4: unknown device + trusted payee = 15 pts (not 60 pts)
            if is_trusted:
                layer5_score += 15
                flags.append("First time using this device ID, but payee is trusted")
            else:
                layer5_score += 60
                flags.append("First time using this device ID, payee is unknown")
                
        # Impossible Travel Check
        travel_warning_score, travel_warnings = check_impossible_travel(user_id, latitude, longitude, now)
        if travel_warning_score > 0:
            if is_trusted:
                layer5_score += 10
                flags.append("Impossible travel velocity anomaly, but payee is trusted")
            else:
                layer5_score += 35
                flags.append(f"Impossible travel velocity anomaly: {travel_warnings[0]}")
                
        # Geofence Check (+20/+40 penalties; skipped if accuracy_m > 5000)
        if geo_score > 0:
            layer5_score += geo_score
            flags.extend(geo_warns)

        # Biometric input check
        if biometric_failed:
            layer5_score += 25
            flags.append("Biometric verification (FaceID/Fingerprint) failed")
            
        layer_scores['compromise'] = float(min(layer5_score, 100.0))

        # ====================================================
        # LAYER 6 — Amount (10% Weight)
        # ====================================================
        layer6_score = 0
        
        # 1. Z-score scaling
        if baseline and baseline.avg_amount and float(baseline.avg_amount) > 0:
            if amount > float(baseline.avg_amount) * 10:
                layer6_score += 90
                flags.append(f"Extreme amount deviation: exceeds 10x your average (Rs. {baseline.avg_amount:.2f})")
            elif amount > float(baseline.avg_amount) * 5:
                layer6_score += 70
                flags.append(f"Large amount deviation: exceeds 5x your average (Rs. {baseline.avg_amount:.2f})")
                
        # 2. Odd hour rounding
        if hour >= 0 and hour <= 5 and amount % 1000 == 0:
            layer6_score += 20
            flags.append("Round amount transaction during odd hour")
            
        # 3. Limit boundaries (Rs. 9,999 / Rs. 99,999 / Rs. 1,00,000 / Rs. 10,000)
        if amount in [9999.0, 99999.0, 10000.0, 100000.0]:
            layer6_score += 15
            flags.append(f"Transaction matches standard regulatory limit boundaries (Rs. {amount})")
            
        layer_scores['amount'] = float(min(layer6_score, 100.0))

        # ====================================================
        # LAYER 7 — Website Trust (2% Weight)
        # ====================================================
        # If receiver UPI corresponds to a merchant site domain, check domain repute
        # Extracts domain from suffix or checks merchant domain if passed
        layer7_score = 0
        website_flagged = False
        domain_to_check = None
        if txn_data.get('merchant_domain'):
            domain_to_check = txn_data['merchant_domain']
        elif "@" in receiver_upi:
            _, provider = receiver_upi.split("@", 1)
            domain_to_check = f"{provider}.com" if not provider.endswith(('.com', '.in', '.org')) else provider

        if domain_to_check:
            wts_score, _, wts_reasons = self.wts.check(domain_to_check)
            layer7_score = wts_score
            for reason in wts_reasons:
                flags.append(f"WTS Reputation alert for domain '{domain_to_check}': {reason}")
                if "Google Safe Browsing" in reason or "OpenPhish" in reason:
                    website_flagged = True

        layer_scores['website_trust'] = float(min(layer7_score, 100.0))

        # ====================================================
        # TOTAL SCORE AGGREGATION (LEARNED FUSION / STATIC FALLBACK)
        # ====================================================
        fusion_prob, fusion_mode, model_agreement_conf = get_fusion_prediction(
            model_probs=model_probs,
            layer_scores=layer_scores
        )

        if fusion_mode == "stacking":
            weighted_score = float(fusion_prob * 100.0)
        else:
            # Static weights fallback: 0.38, 0.04, 0.03, 0.28, 0.15, 0.10, 0.02
            weighted_score = (
                (layer_scores['behavioral'] * 0.38) +
                (layer_scores['velocity'] * 0.04) +
                (layer_scores['flow'] * 0.03) +
                (layer_scores['payee'] * 0.28) +
                (layer_scores['compromise'] * 0.15) +
                (layer_scores['amount'] * 0.10) +
                (layer_scores['website_trust'] * 0.02)
            )
        weighted_score = float(np.clip(weighted_score, 0.0, 100.0))

        # Check payee added within last 24h
        payee_added_under_24h = False
        tp = TrustedPayee.query.filter_by(user_id=user_id, payee_upi=receiver_upi).first()
        if tp is None:
            payee_added_under_24h = True
        else:
            added_date = tp.added_date or now
            payee_added_under_24h = (now - added_date).total_seconds() < 86400

        # Construct context for hard-override rules
        is_new_device = bool(device_id not in known_devices) if baseline else True
        override_context = {
            'user_id': user_id,
            'receiver_upi': receiver_upi,
            'amount': amount,
            'is_scam': bool(is_scam_flag),
            'is_scam_flag': bool(is_scam_flag),
            'qr_mismatch': bool(qr_mismatch),
            'qr_payee_mismatch': bool(qr_mismatch),
            'is_impossible_travel': bool(travel_score > 0),
            'is_new_device': is_new_device,
            'website_flagged': bool(website_flagged),
            'is_phishing_domain': bool(website_flagged),
            'is_mule': bool(is_mule),
            'is_mule_candidate': bool(is_mule),
            'is_new_payee': bool(is_new_payee),
            'amount_over_5x_avg': bool(amount > avg_amt * 5.0) if avg_amt > 0 else False,
            'amount_over_10x_avg': bool(amount > avg_amt * 10.0) if avg_amt > 0 else False,
            'payee_added_under_24h': bool(payee_added_under_24h),
            'payee_added_under_24h_amount_over_5k': bool(amount > 5000.0 and payee_added_under_24h),
            'is_velocity_burst': bool(txn_count_10m > 3 or layer_scores.get('velocity', 0.0) >= 80.0)
        }

        # Post-scoring hard-override evaluation
        final_score, override_applied, override_reasons = evaluate_overrides(
            layer_scores=layer_scores,
            features=engineered_features,
            context=override_context,
            weighted_score=weighted_score
        )

        # Rapid velocity burst heuristic (>= 4 txns in 10 min requires step-up OTP)
        if txn_count_10m > 3:
            final_score = max(final_score, 65.0)
            burst_msg = f"Rapid velocity burst detected: {txn_count_10m} transactions in last 10 minutes"
            if burst_msg not in flags:
                flags.insert(0, burst_msg)

        # Determine final status verdict based on thresholds
        # 0–39   → APPROVED
        # 40–59  → APPROVED_WITH_WARNING
        # 60–79  → REQUIRES_2FA
        # 80–100 → BLOCKED
        if final_score >= 80.0:
            status = 'BLOCKED'
        elif final_score >= 60.0:
            status = 'REQUIRES_2FA'
        elif final_score >= 40.0:
            status = 'APPROVED_WITH_WARNING'
        else:
            status = 'APPROVED'

        # Generate human-readable top reasons
        top_reasons = []
        if override_applied:
            top_reasons.extend(override_reasons)
        for flag in flags:
            if flag not in top_reasons and len(top_reasons) < 5:
                top_reasons.append(flag)
        if not top_reasons:
            top_reasons.append("No anomalies detected.")

        # Explainability via cached SHAP TreeExplainer (Part 25)
        from predictor import explain_prediction_shap, get_plain_language_reason
        top_5_shap = explain_prediction_shap(engineered_features, top_k=5)
        plain_reason = get_plain_language_reason(top_5_shap, status=status)

        return {
            'success': True,
            'status': status,
            'weighted_score': round(weighted_score, 2),
            'final_score': round(final_score, 2),
            'risk_score': round(final_score, 2),
            'override_applied': override_applied,
            'override_reasons': override_reasons,
            'verdict': 'SAFE' if status in ['APPROVED', 'APPROVED_WITH_WARNING'] else ('CAUTION' if status == 'REQUIRES_2FA' else 'FRAUD'),
            'layers': {
                'behavioral': round(layer_scores['behavioral'], 1),
                'velocity': round(layer_scores['velocity'], 1),
                'flow': round(layer_scores['flow'], 1),
                'payee': round(layer_scores['payee'], 1),
                'compromise': round(layer_scores['compromise'], 1),
                'amount': round(layer_scores['amount'], 1),
                'website_trust': round(layer_scores['website_trust'], 1)
            },
            'flags': flags,
            'top_reasons': top_reasons,
            'top_5_features': top_5_shap,
            'shap_explanations': top_5_shap,
            'plain_language_reason': plain_reason,
            'ensemble_confidence': round(ensemble_conf, 4),
            'model_agreement_confidence': round(model_agreement_conf, 4),
            'fusion_mode': fusion_mode,
            'requires_otp': status == 'REQUIRES_2FA',
            'timestamp': datetime.utcnow().isoformat()
        }

# Singleton instance of detection engine
global_fraud_detector = FraudDetectionEngine()
