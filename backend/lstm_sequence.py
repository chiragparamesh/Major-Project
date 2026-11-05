import numpy as np
import pandas as pd
from database import Transaction
import logging

logger = logging.getLogger(__name__)

def create_lstm_sequences(data_matrix: np.ndarray, labels: np.ndarray = None, timesteps: int = 5) -> tuple:
    """
    Transforms 2D tabular transaction data into 3D sequence tensors of shape
    (samples, timesteps, features) suitable for recurrent LSTM networks.
    Highly optimized vectorized implementation.
    """
    samples = data_matrix.shape[0]
    features = data_matrix.shape[1]
    
    # Pre-allocate 3D sequence matrix
    X_seq = np.zeros((samples, timesteps, features))
    
    # Fill sliding window t=0 to timesteps-2 with data_matrix + generated noise
    for t in range(timesteps - 1):
        noise_factor = (timesteps - 1 - t) * 0.05
        # Vectorized noise generation for all samples at once
        noise = np.random.normal(0.0, noise_factor, size=(samples, features))
        X_seq[:, t, :] = data_matrix + noise
        
    # The last timestep t = timesteps-1 is exactly the original data_matrix
    X_seq[:, -1, :] = data_matrix
        
    if labels is not None:
        return X_seq, np.array(labels)
        
    return X_seq

def get_user_txn_sequence(user_id: str, current_features: np.ndarray, timesteps: int = 5) -> np.ndarray:
    """
    Fetches the last N-1 transactions for a user from the database, processes them,
    and appends the current transaction's features to form a 3D sequence tensor
    of shape (1, timesteps, features) for real-time LSTM inference.
    """
    features_dim = len(current_features)
    
    # Initialize a 3D array of zeros
    sequence = np.zeros((1, timesteps, features_dim))
    
    try:
        # Query last N-1 transactions from the DB
        # For simplicity, we fallback to synthetic history if database transactions are sparse
        txns = Transaction.query.filter_by(user_id=user_id)\
                                .filter(Transaction.status.in_(['APPROVED', 'APPROVED_WITH_WARNING']))\
                                .order_by(Transaction.created_at.desc())\
                                .limit(timesteps - 1)\
                                .all()
                                
        # Reverse to get chronological order
        txns.reverse()
        
        rows = []
        # Convert DB transactions to scaled feature vectors
        # Note: In production, we'd pull features from DB columns.
        # If we have less history, we fill with current_features + slight noise.
        history_needed = timesteps - 1 - len(txns)
        
        for _ in range(history_needed):
            # Pad with modified current features (simulate history)
            noise = np.random.normal(0, 0.02, size=features_dim)
            rows.append(current_features + noise)
            
        for txn in txns:
            # Map database txn values to feature format
            # Standard mappings:
            row = np.zeros(features_dim)
            row[0] = float(txn.amount)
            row[1] = int(txn.hour) if txn.hour is not None else 12
            row[2] = int(txn.day_of_week) if txn.day_of_week is not None else 0
            row[3] = 1 if txn.is_holiday else 0
            # Populate remaining features with reasonable baseline approximations
            row[4] = 1 if row[2] >= 5 else 0  # Weekend
            row[5] = 1.0  # amount_vs_avg_ratio
            row[6] = 0.0  # amount_vs_std_zscore
            row[7] = 1    # txn_count_last_hour
            row[8] = 2    # txn_count_last_24h
            row[12] = 1   # known_device_flag
            row[17] = 1.0 # distance_from_home_km
            rows.append(row)
            
        # Append current transaction features
        rows.append(current_features)
        
        # Add to sequence tensor
        sequence[0] = np.array(rows)
        
    except Exception as e:
        logger.error(f"Error building transaction sequence for LSTM: {e}")
        # Complete fallback: fill sequence with copies of current features
        for t in range(timesteps):
            sequence[0, t] = current_features
            
    return sequence
