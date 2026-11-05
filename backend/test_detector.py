import os
import sys
from datetime import datetime, timedelta

# Import project modules
from app import create_app
from db import db
from database import User, Transaction, UserBehaviorBaseline, TrustedPayee, ScamUpi
from security import hash_pin, encrypt_val
from fraud_detection import global_fraud_detector

def run_e2e_tests():
    print("="*60)
    print("      [TESTS] RUNNING MLBFD 7-LAYER ENGINE E2E TESTS [TESTS]      ")
    print("="*60)
    
    app = create_app()
    with app.app_context():
        # Clean up existing test data
        print("Cleaning up old test data...")
        Transaction.query.filter_by(user_id='chirag_test').delete()
        TrustedPayee.query.filter_by(user_id='chirag_test').delete()
        UserBehaviorBaseline.query.filter_by(user_id='chirag_test').delete()
        User.query.filter_by(user_id='chirag_test').delete()
        ScamUpi.query.filter_by(upi_id='scammer@okaxis').delete()
        
        # Add a blacklisted scam UPI
        scam = ScamUpi.query.filter_by(upi_id='scammer@okaxis').first()
        if not scam:
            scam = ScamUpi(upi_id='scammer@okaxis', reported_count=5, verified=True)
            db.session.add(scam)
            
        db.session.commit()

        # 1. Create a Test User
        print("\n[SETUP] Creating test user 'chirag_test'...")
        pin_hash = hash_pin("1234")
        test_user = User(
            user_id='chirag_test',
            pin_hash=pin_hash,
            balance=100000.00,
            phone_number="+919876543210",
            device_token="fcm_token_chirag_test",
            home_latitude=12.9716, # Bangalore coords
            home_longitude=77.5946
        )
        db.session.add(test_user)
        db.session.commit()

        # 2. Establish Behavior Baseline
        print("[SETUP] Establishing user behavior baseline...")
        baseline = UserBehaviorBaseline(
            user_id='chirag_test',
            avg_amount=1000.00,
            std_amount=100.00,
            avg_hour=14.5,
            txn_count=10,
            known_devices=['device_chirag_phone'],
            known_payees=['friend@okaxis', 'mom@okaxis'],
            mcc_history={'5411': 5, '5812': 5}
        )
        db.session.add(baseline)
        
        # Seed a trusted payee
        trusted = TrustedPayee(
            user_id='chirag_test',
            payee_upi='friend@okaxis',
            nickname='Friend',
            txn_count=4,
            total_amount=4000.00
        )
        db.session.add(trusted)
        db.session.commit()

        print("Setup complete! Baseline average amount: Rs. 1,000.00")

        # ----------------------------------------------------
        # TEST CASE 1: SAFE TRANSACTION
        # ----------------------------------------------------
        print("\n" + "-"*40)
        print(" TEST 1: Safe Scenario (Approved)")
        print("-"*40)
        payload1 = {
            'user_id': 'chirag_test',
            'sender_upi': 'chirag@okaxis',
            'receiver_upi': 'friend@okaxis', # Trusted payee
            'amount': 250.00, # Small amount
            'device_id': 'device_chirag_phone', # Known device
            'latitude': 12.9718, # Close to home location
            'longitude': 77.5948,
            'biometric_failed': False,
            'qr_code': '',
            'mcc_code': '5411'
        }
        
        verdict1 = global_fraud_detector.detect(payload1)
        print(f"Risk Score: {verdict1['risk_score']}%")
        print(f"Verdict Status: {verdict1['status']}")
        print(f"Flags Triggered: {verdict1['flags']}")
        assert verdict1['status'] == 'APPROVED', f"Expected APPROVED but got {verdict1['status']}"
        print(" TEST 1 PASSED!")

        # ----------------------------------------------------
        # TEST CASE 2: CAUTION SCENARIO
        # ----------------------------------------------------
        print("\n" + "-"*40)
        print(" TEST 2: Caution Scenario (Approved with Warning)")
        print("-"*40)
        payload2 = {
            'user_id': 'chirag_test',
            'sender_upi': 'chirag@okaxis',
            'receiver_upi': 'mom@okaxis', # Known but not trusted yet (txn_count < 3)
            'amount': 5500.00, # 5.5x Average (trips amount warning)
            'device_id': 'device_chirag_phone',
            'latitude': 12.9716,
            'longitude': 77.5946,
            'biometric_failed': False,
            'qr_code': '',
            'mcc_code': '5411'
        }
        
        verdict2 = global_fraud_detector.detect(payload2)
        print(f"Risk Score: {verdict2['risk_score']}%")
        print(f"Verdict Status: {verdict2['status']}")
        print(f"Flags Triggered: {verdict2['flags']}")
        assert verdict2['status'] == 'APPROVED_WITH_WARNING', f"Expected APPROVED_WITH_WARNING but got {verdict2['status']}"
        print(" TEST 2 PASSED!")

        # ----------------------------------------------------
        # TEST CASE 3: SUSPICIOUS SCENARIO
        # ----------------------------------------------------
        print("\n" + "-"*40)
        print(" TEST 3: Suspicious Scenario (Requires 2FA)")
        print("-"*40)
        payload3 = {
            'user_id': 'chirag_test',
            'sender_upi': 'chirag@okaxis',
            'receiver_upi': 'unknown_merchant@okicici', # Unknown payee
            'amount': 6500.00, # 6.5x average
            'device_id': 'unknown_device_xyz', # Unknown device (adds 60 pts to compromise layer)
            'latitude': 12.9716,
            'longitude': 77.5946,
            'biometric_failed': False,
            'qr_code': '',
            'mcc_code': '7995' # High risk MCC (Gambling)
        }
        
        verdict3 = global_fraud_detector.detect(payload3)
        print(f"Risk Score: {verdict3['risk_score']}%")
        print(f"Verdict Status: {verdict3['status']}")
        print(f"Flags Triggered: {verdict3['flags']}")
        assert verdict3['status'] == 'REQUIRES_2FA', f"Expected REQUIRES_2FA but got {verdict3['status']}"
        print(" TEST 3 PASSED!")

        # ----------------------------------------------------
        # TEST CASE 4: FRAUD SCENARIO
        # ----------------------------------------------------
        print("\n" + "-"*40)
        print(" TEST 4: Fraud Scenario (Blocked)")
        print("-"*40)
        payload4 = {
            'user_id': 'chirag_test',
            'sender_upi': 'chirag@okaxis',
            'receiver_upi': 'scammer@okaxis', # Blacklisted Scam UPI
            'amount': 15000.00, # High amount
            'device_id': 'malicious_emulator',
            'latitude': 40.7128, # New York City (Impossible Travel from Bangalore coords)
            'longitude': -74.0060,
            'biometric_failed': True, # Failed biometrics
            'qr_code': 'upi://pay?pa=scammer@okaxis&pn=Scammer&am=15000&mam=15000',
            'mcc_code': '6051' # Cryptocoin MCC
        }
        
        verdict4 = global_fraud_detector.detect(payload4)
        print(f"Risk Score: {verdict4['risk_score']}%")
        print(f"Verdict Status: {verdict4['status']}")
        print(f"Flags Triggered: {verdict4['flags']}")
        assert verdict4['status'] == 'BLOCKED', f"Expected BLOCKED but got {verdict4['status']}"
        print(" TEST 4 PASSED!")

        print("\n" + "="*60)
        print("      [SUCCESS] ALL 7-LAYER FRAUD DETECTOR TESTS PASSED! [SUCCESS]      ")
        print("="*60 + "\n")

if __name__ == '__main__':
    run_e2e_tests()
