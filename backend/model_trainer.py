import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
import tensorflow as tf
tf.config.threading.set_intra_op_parallelism_threads(1)
tf.config.threading.set_inter_op_parallelism_threads(1)
from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.layers import Dense, LSTM, Input, Dropout, Layer, GlobalAveragePooling1D
from tensorflow.keras import backend as K
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.linear_model import LogisticRegression
import numpy as np

# Focal Loss Implementation for handling severe class imbalance
@tf.keras.utils.register_keras_serializable()
class BinaryFocalLoss(tf.keras.losses.Loss):
    def __init__(self, gamma=2., alpha=.25, **kwargs):
        super(BinaryFocalLoss, self).__init__(**kwargs)
        self.gamma = gamma
        self.alpha = alpha

    def call(self, y_true, y_pred):
        y_true = tf.cast(y_true, tf.float32)
        y_pred = K.clip(y_pred, K.epsilon(), 1.0 - K.epsilon())
        
        cross_entropy = -y_true * K.log(y_pred)
        weight = y_true * self.alpha * K.pow(1. - y_pred, self.gamma)
        
        cross_entropy_neg = -(1.0 - y_true) * K.log(1.0 - y_pred)
        weight_neg = (1.0 - y_true) * (1.0 - self.alpha) * K.pow(y_pred, self.gamma)
        
        return K.mean(weight * cross_entropy + weight_neg * cross_entropy_neg)

    def get_config(self):
        config = super(BinaryFocalLoss, self).get_config()
        config.update({
            "gamma": self.gamma,
            "alpha": self.alpha
        })
        return config

# Custom self-Attention layer for LSTM sequence processing
@tf.keras.utils.register_keras_serializable()
class AttentionLayer(Layer):
    def __init__(self, **kwargs):
        super(AttentionLayer, self).__init__(**kwargs)

    def build(self, input_shape):
        # Weight shape: (features, 1)
        self.W = self.add_weight(
            name="att_weight",
            shape=(input_shape[-1], 1),
            initializer="glorot_uniform",
            trainable=True
        )
        self.b = self.add_weight(
            name="att_bias",
            shape=(input_shape[1], 1),
            initializer="zeros",
            trainable=True
        )
        super(AttentionLayer, self).build(input_shape)

    def call(self, x):
        # Input x shape: (batch, timesteps, features)
        # Dot product with W + bias
        et = tf.squeeze(tf.matmul(x, self.W) + self.b, axis=-1)  # shape: (batch, timesteps)
        at = tf.nn.softmax(et, axis=-1)  # shape: (batch, timesteps)
        at = tf.expand_dims(at, axis=-1)  # shape: (batch, timesteps, 1)
        
        # Weighted reduction sum over timesteps
        output = x * at
        return tf.reduce_sum(output, axis=1)  # shape: (batch, features)

    def get_config(self):
        config = super(AttentionLayer, self).get_config()
        return config

def build_neural_network(input_dim: int) -> Model:
    """Builds a Dense Deep Neural Network (DNN) with Focal Loss compiler"""
    inputs = Input(shape=(input_dim,))
    x = Dense(128, activation='relu')(inputs)
    x = Dropout(0.3)(x)
    x = Dense(64, activation='relu')(x)
    x = Dropout(0.2)(x)
    x = Dense(32, activation='relu')(x)
    outputs = Dense(1, activation='sigmoid')(x)
    
    model = Model(inputs=inputs, outputs=outputs, name="DNN_Fraud_Classifier")
    model.compile(
        optimizer='adam',
        loss=BinaryFocalLoss(gamma=2.0, alpha=0.25),
        metrics=['accuracy', tf.keras.metrics.AUC(name='auc')]
    )
    return model

def build_lstm_model(timesteps: int, features: int) -> Model:
    """Builds an LSTM sequence model with a self-attention reduction layer"""
    inputs = Input(shape=(timesteps, features))
    x = LSTM(64, return_sequences=True)(inputs)
    x = Dropout(0.2)(x)
    x = LSTM(32, return_sequences=True)(x)
    x = AttentionLayer()(x)
    x = Dense(16, activation='relu')(x)
    outputs = Dense(1, activation='sigmoid')(x)
    
    model = Model(inputs=inputs, outputs=outputs, name="LSTM_Attention_Classifier")
    model.compile(
        optimizer='adam',
        loss='binary_crossentropy',
        metrics=['accuracy', tf.keras.metrics.AUC(name='auc')]
    )
    return model

def build_autoencoder_model(input_dim: int) -> Model:
    """Builds a Deep Reconstruction Autoencoder for unsupervised anomaly detection"""
    inputs = Input(shape=(input_dim,))
    
    # Encoder
    x = Dense(128, activation='relu')(inputs)
    x = Dropout(0.2)(x)
    x = Dense(64, activation='relu')(x)
    x = Dense(32, activation='relu')(x)
    bottleneck = Dense(16, activation='relu', name="autoencoder_bottleneck")(x)
    
    # Decoder
    x = Dense(32, activation='relu')(bottleneck)
    x = Dense(64, activation='relu')(x)
    x = Dense(128, activation='relu')(x)
    outputs = Dense(input_dim, activation='linear')(x)
    
    autoencoder = Model(inputs=inputs, outputs=outputs, name="Autoencoder_Anomaly_Detector")
    autoencoder.compile(
        optimizer='adam',
        loss='mean_squared_error',
        metrics=['mae']
    )
    return autoencoder

def get_xgboost_classifier():
    """Returns an un-fitted XGBoost Classifier"""
    return xgb.XGBClassifier(
        n_estimators=150,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        device='cpu', # CPU core computation to support all hardware environments
        n_jobs=1
    )

def get_random_forest_classifier():
    """Returns a scikit-learn Random Forest Classifier"""
    return RandomForestClassifier(
        n_estimators=100,
        max_depth=12,
        min_samples_split=5,
        random_state=42,
        n_jobs=1
    )

def get_logistic_regression():
    """Returns a Logistic Regression baseline model"""
    return LogisticRegression(
        max_iter=1000,
        solver='lbfgs',
        class_weight='balanced',
        random_state=42,
        n_jobs=1
    )

def get_isolation_forest():
    """Returns an Isolation Forest anomaly detector"""
    return IsolationForest(
        n_estimators=100,
        contamination=0.05,
        random_state=42,
        n_jobs=1
    )
