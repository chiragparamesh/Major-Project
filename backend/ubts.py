import logging
import math
from datetime import datetime
from db import db
from database import UserBehaviorBaseline

logger = logging.getLogger(__name__)

def update_user_baseline(user_id: str, amount: float, hour: int, device_id: str, payee_upi: str, mcc_code: str):
    """
    Updates the rolling behavioral baseline of a user in the user_behavior_baseline table
    after a successful or approved transaction.
    """
    try:
        baseline = UserBehaviorBaseline.query.filter_by(user_id=user_id).first()
        
        # If no baseline exists, initialize a new record
        if not baseline:
            baseline = UserBehaviorBaseline(
                user_id=user_id,
                avg_amount=amount,
                std_amount=0.0,
                avg_hour=float(hour),
                txn_count=1,
                known_devices=[device_id] if device_id else [],
                known_payees=[payee_upi] if payee_upi else [],
                mcc_history={mcc_code: 1} if mcc_code else {}
            )
            db.session.add(baseline)
            db.session.commit()
            logger.info(f"Initialized new baseline tracker for user {user_id}")
            return
            
        # Update running averages and statistics
        old_count = int(baseline.txn_count or 0)
        new_count = old_count + 1
        baseline.txn_count = new_count
        
        # Running average amount
        old_avg = float(baseline.avg_amount or 0.0)
        new_avg = ((old_avg * old_count) + float(amount)) / new_count
        baseline.avg_amount = new_avg
        
        # Running population std via Welford on the VARIANCE (the old code applied the
        # variance update to the std itself, mixing units and inflating std -> tiny z-scores).
        old_var = float(baseline.std_amount or 0.0) ** 2
        diff = float(amount) - old_avg
        new_var = old_var + (diff * (float(amount) - new_avg) - old_var) / new_count
        baseline.std_amount = math.sqrt(max(0.0, new_var))
        
        # Running average hour (circular coordinates would be ideal, but linear avg suffices for range)
        old_avg_hour = float(baseline.avg_hour or 12.0)
        new_avg_hour = ((old_avg_hour * old_count) + float(hour)) / new_count
        baseline.avg_hour = new_avg_hour
        
        # Update known devices (JSON array)
        devices = list(baseline.known_devices or [])
        if device_id and device_id not in devices:
            devices.append(device_id)
            baseline.known_devices = devices
            
        # Update known payees (JSON array)
        payees = list(baseline.known_payees or [])
        if payee_upi and payee_upi not in payees:
            payees.append(payee_upi)
            baseline.known_payees = payees
            
        # Update MCC history (JSON dictionary mapping code -> count)
        mcc_hist = dict(baseline.mcc_history or {})
        if mcc_code:
            mcc_hist[mcc_code] = mcc_hist.get(mcc_code, 0) + 1
            baseline.mcc_history = mcc_hist
            
        baseline.last_updated = datetime.utcnow()
        db.session.commit()
        logger.info(f"Successfully updated baseline tracker for user {user_id} (txn count: {new_count})")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update user baseline for {user_id}: {e}")
