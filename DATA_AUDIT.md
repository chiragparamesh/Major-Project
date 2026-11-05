# MLBFD Comprehensive Dataset Audit & Schema Mapping

*Generated on: 2026-10-25 20:12:16*

## 1. Executive Summary
This document audits all raw financial transaction and fraud datasets residing in `D:\Major Project\Datasets`.
All analyses were executed using strictly chunked data reading (`chunksize=50,000`), guaranteeing zero memory blowup.
This audit provides exhaustive verification of columns, data types, missing value percentages, class balance ratios, temporal timelines, and explicit mapping feasibility against the 22 canonical features of the MLBFD multi-layer fraud detection engine.

Additionally, this audit contains a forensic examination of `backend/data_processor.py` (lines 142–230), documenting the exact lines where synthetic Gaussian overlays were previously injected conditional on the fraud label, explaining how that caused catastrophic data leakage, and specifying how the clean pipeline in Parts 18–21 solves it honestly.

## 2. Dataset Inventory Summary
| Dataset File | Directory Tier | Size (MB) | Total Rows | Columns | Label Column | Fraud Ratio (%) | Temporal Column & Range |
|---|---|---|---|---|---|---|---|
| `PS_20174392719_1491204439457_log.csv` | Tier1 | 470.7 | 6,362,620 | 11 | `isFraud` | 0.1291% (8,213 / 6,362,620) | `step`: [1 .. 743] |
| `train_identity.csv` | Tier1 | 25.3 | 144,233 | 41 | `None` | N/A | None |
| `train_transaction.csv` | Tier1 | 651.7 | 590,540 | 394 | `isFraud` | 3.4990% (20,663 / 590,540) | `TransactionDT`: [86400 .. 15811131] |
| `AIML Dataset.csv` | Tier2 | 470.7 | 6,362,620 | 11 | `isFraud` | 0.1291% (8,213 / 6,362,620) | `step`: [1 .. 743] |
| `Base.csv` | Tier2 | 203.5 | 1,000,000 | 32 | `fraud_bool` | 1.1029% (11,029 / 1,000,000) | `month`: [0 .. 7] |
| `Variant I.csv` | Tier2 | 203.5 | 1,000,000 | 32 | `fraud_bool` | 1.1029% (11,029 / 1,000,000) | `month`: [0 .. 7] |
| `Variant II.csv` | Tier2 | 203.6 | 1,000,000 | 32 | `fraud_bool` | 1.1029% (11,029 / 1,000,000) | `month`: [0 .. 7] |
| `Variant III.csv` | Tier2 | 240.5 | 1,000,000 | 34 | `fraud_bool` | 1.1030% (11,030 / 1,000,000) | `month`: [0 .. 7] |
| `Variant IV.csv` | Tier2 | 203.6 | 1,000,000 | 32 | `fraud_bool` | 1.1030% (11,030 / 1,000,000) | `month`: [0 .. 7] |
| `Variant V.csv` | Tier2 | 240.5 | 1,000,000 | 34 | `fraud_bool` | 1.1030% (11,030 / 1,000,000) | `month`: [0 .. 7] |
| `synthetic_mobile_money_transaction_dataset.csv` | Tier2 | 149.3 | 1,720,181 | 10 | `isFraud` | 10.2035% (175,518 / 1,720,181) | `step`: [0 .. 143] |

## 3. Detailed Audit Per Dataset

### 3.1 `PS_20174392719_1491204439457_log.csv`
- **Path**: `D:\Major Project\Datasets\Tier1\PS_20174392719_1491204439457_log.csv`
- **File Size**: 470.67 MB
- **Row Count**: 6,362,620 rows
- **Column Count**: 11 columns
- **Ground Truth Label**: `isFraud`
- **Class Distribution**: Fraud = 8,213 (0.1291%), Legitimate = 6,354,407 (99.8709%)
- **Temporal Column**: `step` spanning 1.0 to 743.0
- **Missing Value Profile**: 0 of 11 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `step` | `int64` | 0.00% |
| `type` | `object` | 0.00% |
| `amount` | `float64` | 0.00% |
| `nameOrig` | `object` | 0.00% |
| `oldbalanceOrg` | `float64` | 0.00% |
| `newbalanceOrig` | `float64` | 0.00% |
| `nameDest` | `object` | 0.00% |
| `oldbalanceDest` | `float64` | 0.00% |
| `newbalanceDest` | `float64` | 0.00% |
| `isFraud` | `int64` | 0.00% |
| `isFlaggedFraud` | `int64` | 0.00% |


### 3.2 `train_identity.csv`
- **Path**: `D:\Major Project\Datasets\Tier1\train_identity.csv`
- **File Size**: 25.30 MB
- **Row Count**: 144,233 rows
- **Column Count**: 41 columns
- **Ground Truth Label**: `None`
- **Missing Value Profile**: 38 of 41 columns contain missing values.
  - Top missing columns:
    - `id_24` (float64): 96.71% missing
    - `id_25` (float64): 96.44% missing
    - `id_07` (float64): 96.43% missing
    - `id_08` (float64): 96.43% missing
    - `id_21` (float64): 96.42% missing
    - `id_26` (float64): 96.42% missing
    - `id_22` (float64): 96.42% missing
    - `id_23` (object): 96.42% missing

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `TransactionID` | `int64` | 0.00% |
| `id_01` | `float64` | 0.00% |
| `id_02` | `float64` | 2.33% |
| `id_03` | `float64` | 54.02% |
| `id_04` | `float64` | 54.02% |
| `id_05` | `float64` | 5.11% |
| `id_06` | `float64` | 5.11% |
| `id_07` | `float64` | 96.43% |
| `id_08` | `float64` | 96.43% |
| `id_09` | `float64` | 48.05% |
| `id_10` | `float64` | 48.05% |
| `id_11` | `float64` | 2.26% |
| `id_12` | `object` | 0.00% |
| `id_13` | `float64` | 11.73% |
| `id_14` | `float64` | 44.50% |
| *... and 26 additional columns* | | |


### 3.3 `train_transaction.csv`
- **Path**: `D:\Major Project\Datasets\Tier1\train_transaction.csv`
- **File Size**: 651.69 MB
- **Row Count**: 590,540 rows
- **Column Count**: 394 columns
- **Ground Truth Label**: `isFraud`
- **Class Distribution**: Fraud = 20,663 (3.4990%), Legitimate = 569,877 (96.5010%)
- **Temporal Column**: `TransactionDT` spanning 86400.0 to 15811131.0
- **Missing Value Profile**: 374 of 394 columns contain missing values.
  - Top missing columns:
    - `dist2` (float64): 93.63% missing
    - `D7` (float64): 93.41% missing
    - `D13` (float64): 89.51% missing
    - `D14` (float64): 89.47% missing
    - `D12` (float64): 89.04% missing
    - `D6` (float64): 87.61% missing
    - `D8` (float64): 87.31% missing
    - `D9` (float64): 87.31% missing

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `TransactionID` | `int64` | 0.00% |
| `isFraud` | `int64` | 0.00% |
| `TransactionDT` | `int64` | 0.00% |
| `TransactionAmt` | `float64` | 0.00% |
| `ProductCD` | `object` | 0.00% |
| `card1` | `int64` | 0.00% |
| `card2` | `float64` | 1.51% |
| `card3` | `float64` | 0.27% |
| `card4` | `object` | 0.27% |
| `card5` | `float64` | 0.72% |
| `card6` | `object` | 0.27% |
| `addr1` | `float64` | 11.13% |
| `addr2` | `float64` | 11.13% |
| `dist1` | `float64` | 59.65% |
| `dist2` | `float64` | 93.63% |
| *... and 379 additional columns* | | |


### 3.4 `AIML Dataset.csv`
- **Path**: `D:\Major Project\Datasets\Tier2\AIML Dataset.csv`
- **File Size**: 470.67 MB
- **Row Count**: 6,362,620 rows
- **Column Count**: 11 columns
- **Ground Truth Label**: `isFraud`
- **Class Distribution**: Fraud = 8,213 (0.1291%), Legitimate = 6,354,407 (99.8709%)
- **Temporal Column**: `step` spanning 1.0 to 743.0
- **Missing Value Profile**: 0 of 11 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `step` | `int64` | 0.00% |
| `type` | `object` | 0.00% |
| `amount` | `float64` | 0.00% |
| `nameOrig` | `object` | 0.00% |
| `oldbalanceOrg` | `float64` | 0.00% |
| `newbalanceOrig` | `float64` | 0.00% |
| `nameDest` | `object` | 0.00% |
| `oldbalanceDest` | `float64` | 0.00% |
| `newbalanceDest` | `float64` | 0.00% |
| `isFraud` | `int64` | 0.00% |
| `isFlaggedFraud` | `int64` | 0.00% |


### 3.5 `Base.csv`
- **Path**: `D:\Major Project\Datasets\Tier2\Base.csv`
- **File Size**: 203.54 MB
- **Row Count**: 1,000,000 rows
- **Column Count**: 32 columns
- **Ground Truth Label**: `fraud_bool`
- **Class Distribution**: Fraud = 11,029 (1.1029%), Legitimate = 988,971 (98.8971%)
- **Temporal Column**: `month` spanning 0.0 to 7.0
- **Missing Value Profile**: 0 of 32 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `fraud_bool` | `int64` | 0.00% |
| `income` | `float64` | 0.00% |
| `name_email_similarity` | `float64` | 0.00% |
| `prev_address_months_count` | `int64` | 0.00% |
| `current_address_months_count` | `int64` | 0.00% |
| `customer_age` | `int64` | 0.00% |
| `days_since_request` | `float64` | 0.00% |
| `intended_balcon_amount` | `float64` | 0.00% |
| `payment_type` | `object` | 0.00% |
| `zip_count_4w` | `int64` | 0.00% |
| `velocity_6h` | `float64` | 0.00% |
| `velocity_24h` | `float64` | 0.00% |
| `velocity_4w` | `float64` | 0.00% |
| `bank_branch_count_8w` | `int64` | 0.00% |
| `date_of_birth_distinct_emails_4w` | `int64` | 0.00% |
| *... and 17 additional columns* | | |


### 3.6 `Variant I.csv`
- **Path**: `D:\Major Project\Datasets\Tier2\Variant I.csv`
- **File Size**: 203.51 MB
- **Row Count**: 1,000,000 rows
- **Column Count**: 32 columns
- **Ground Truth Label**: `fraud_bool`
- **Class Distribution**: Fraud = 11,029 (1.1029%), Legitimate = 988,971 (98.8971%)
- **Temporal Column**: `month` spanning 0.0 to 7.0
- **Missing Value Profile**: 0 of 32 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `fraud_bool` | `int64` | 0.00% |
| `income` | `float64` | 0.00% |
| `name_email_similarity` | `float64` | 0.00% |
| `prev_address_months_count` | `int64` | 0.00% |
| `current_address_months_count` | `int64` | 0.00% |
| `customer_age` | `int64` | 0.00% |
| `days_since_request` | `float64` | 0.00% |
| `intended_balcon_amount` | `float64` | 0.00% |
| `payment_type` | `object` | 0.00% |
| `zip_count_4w` | `int64` | 0.00% |
| `velocity_6h` | `float64` | 0.00% |
| `velocity_24h` | `float64` | 0.00% |
| `velocity_4w` | `float64` | 0.00% |
| `bank_branch_count_8w` | `int64` | 0.00% |
| `date_of_birth_distinct_emails_4w` | `int64` | 0.00% |
| *... and 17 additional columns* | | |


### 3.7 `Variant II.csv`
- **Path**: `D:\Major Project\Datasets\Tier2\Variant II.csv`
- **File Size**: 203.65 MB
- **Row Count**: 1,000,000 rows
- **Column Count**: 32 columns
- **Ground Truth Label**: `fraud_bool`
- **Class Distribution**: Fraud = 11,029 (1.1029%), Legitimate = 988,971 (98.8971%)
- **Temporal Column**: `month` spanning 0.0 to 7.0
- **Missing Value Profile**: 0 of 32 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `fraud_bool` | `int64` | 0.00% |
| `income` | `float64` | 0.00% |
| `name_email_similarity` | `float64` | 0.00% |
| `prev_address_months_count` | `int64` | 0.00% |
| `current_address_months_count` | `int64` | 0.00% |
| `customer_age` | `int64` | 0.00% |
| `days_since_request` | `float64` | 0.00% |
| `intended_balcon_amount` | `float64` | 0.00% |
| `payment_type` | `object` | 0.00% |
| `zip_count_4w` | `int64` | 0.00% |
| `velocity_6h` | `float64` | 0.00% |
| `velocity_24h` | `float64` | 0.00% |
| `velocity_4w` | `float64` | 0.00% |
| `bank_branch_count_8w` | `int64` | 0.00% |
| `date_of_birth_distinct_emails_4w` | `int64` | 0.00% |
| *... and 17 additional columns* | | |


### 3.8 `Variant III.csv`
- **Path**: `D:\Major Project\Datasets\Tier2\Variant III.csv`
- **File Size**: 240.52 MB
- **Row Count**: 1,000,000 rows
- **Column Count**: 34 columns
- **Ground Truth Label**: `fraud_bool`
- **Class Distribution**: Fraud = 11,030 (1.1030%), Legitimate = 988,970 (98.8970%)
- **Temporal Column**: `month` spanning 0.0 to 7.0
- **Missing Value Profile**: 0 of 34 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `fraud_bool` | `int64` | 0.00% |
| `income` | `float64` | 0.00% |
| `name_email_similarity` | `float64` | 0.00% |
| `prev_address_months_count` | `int64` | 0.00% |
| `current_address_months_count` | `int64` | 0.00% |
| `customer_age` | `int64` | 0.00% |
| `days_since_request` | `float64` | 0.00% |
| `intended_balcon_amount` | `float64` | 0.00% |
| `payment_type` | `object` | 0.00% |
| `zip_count_4w` | `int64` | 0.00% |
| `velocity_6h` | `float64` | 0.00% |
| `velocity_24h` | `float64` | 0.00% |
| `velocity_4w` | `float64` | 0.00% |
| `bank_branch_count_8w` | `int64` | 0.00% |
| `date_of_birth_distinct_emails_4w` | `int64` | 0.00% |
| *... and 19 additional columns* | | |


### 3.9 `Variant IV.csv`
- **Path**: `D:\Major Project\Datasets\Tier2\Variant IV.csv`
- **File Size**: 203.65 MB
- **Row Count**: 1,000,000 rows
- **Column Count**: 32 columns
- **Ground Truth Label**: `fraud_bool`
- **Class Distribution**: Fraud = 11,030 (1.1030%), Legitimate = 988,970 (98.8970%)
- **Temporal Column**: `month` spanning 0.0 to 7.0
- **Missing Value Profile**: 0 of 32 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `fraud_bool` | `int64` | 0.00% |
| `income` | `float64` | 0.00% |
| `name_email_similarity` | `float64` | 0.00% |
| `prev_address_months_count` | `int64` | 0.00% |
| `current_address_months_count` | `int64` | 0.00% |
| `customer_age` | `int64` | 0.00% |
| `days_since_request` | `float64` | 0.00% |
| `intended_balcon_amount` | `float64` | 0.00% |
| `payment_type` | `object` | 0.00% |
| `zip_count_4w` | `int64` | 0.00% |
| `velocity_6h` | `float64` | 0.00% |
| `velocity_24h` | `float64` | 0.00% |
| `velocity_4w` | `float64` | 0.00% |
| `bank_branch_count_8w` | `int64` | 0.00% |
| `date_of_birth_distinct_emails_4w` | `int64` | 0.00% |
| *... and 17 additional columns* | | |


### 3.10 `Variant V.csv`
- **Path**: `D:\Major Project\Datasets\Tier2\Variant V.csv`
- **File Size**: 240.53 MB
- **Row Count**: 1,000,000 rows
- **Column Count**: 34 columns
- **Ground Truth Label**: `fraud_bool`
- **Class Distribution**: Fraud = 11,030 (1.1030%), Legitimate = 988,970 (98.8970%)
- **Temporal Column**: `month` spanning 0.0 to 7.0
- **Missing Value Profile**: 0 of 34 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `fraud_bool` | `int64` | 0.00% |
| `income` | `float64` | 0.00% |
| `name_email_similarity` | `float64` | 0.00% |
| `prev_address_months_count` | `int64` | 0.00% |
| `current_address_months_count` | `int64` | 0.00% |
| `customer_age` | `int64` | 0.00% |
| `days_since_request` | `float64` | 0.00% |
| `intended_balcon_amount` | `float64` | 0.00% |
| `payment_type` | `object` | 0.00% |
| `zip_count_4w` | `int64` | 0.00% |
| `velocity_6h` | `float64` | 0.00% |
| `velocity_24h` | `float64` | 0.00% |
| `velocity_4w` | `float64` | 0.00% |
| `bank_branch_count_8w` | `int64` | 0.00% |
| `date_of_birth_distinct_emails_4w` | `int64` | 0.00% |
| *... and 19 additional columns* | | |


### 3.11 `synthetic_mobile_money_transaction_dataset.csv`
- **Path**: `D:\Major Project\Datasets\Tier2\synthetic_mobile_money_transaction_dataset.csv`
- **File Size**: 149.31 MB
- **Row Count**: 1,720,181 rows
- **Column Count**: 10 columns
- **Ground Truth Label**: `isFraud`
- **Class Distribution**: Fraud = 175,518 (10.2035%), Legitimate = 1,544,663 (89.7965%)
- **Temporal Column**: `step` spanning 0.0 to 143.0
- **Missing Value Profile**: 0 of 10 columns contain missing values.
  - No missing values detected across any column.

**Schema Sample (First 15 Columns & Types):**

| Column Name | Data Type | Missing % |
|---|---|---|
| `step` | `int64` | 0.00% |
| `transactionType` | `object` | 0.00% |
| `amount` | `float64` | 0.00% |
| `initiator` | `int64` | 0.00% |
| `oldBalInitiator` | `float64` | 0.00% |
| `newBalInitiator` | `float64` | 0.00% |
| `recipient` | `object` | 0.00% |
| `oldBalRecipient` | `float64` | 0.00% |
| `newBalRecipient` | `float64` | 0.00% |
| `isFraud` | `int64` | 0.00% |


## 4. Canonical 22 Feature Mapping Matrix
The MLBFD fraud engine operates on 22 canonical features. Below is the honest feasibility mapping across the primary data sources (PaySim, IEEE-CIS, and Bank Account Fraud).

| Feature Index | Feature Name | Description | PaySim | IEEE-CIS | Bank Account Fraud (BAF) |
|---|---|---|---|---|---|
| 1 | `amount` | Feature #1 | **Direct** (Direct column 'amount') | **Direct** (Direct column 'TransactionAmt') | Unavailable (Normalized income and credit risk variables, but exact transaction amount omitted) |
| 2 | `hour` | Feature #2 | **Direct** (hour = step % 24) | **Direct** (hour = (TransactionDT // 3600) % 24) | Unavailable (Only coarse session/time features present) |
| 3 | `day_of_week` | Feature #3 | **Direct** (day_of_week = (step // 24) % 7) | **Direct** (day_of_week = (TransactionDT // 86400) % 7) | Unavailable (Temporal variables masked/coarse) |
| 4 | `is_holiday` | Feature #4 | *Approx* (Simulated/approximated from Indian holiday calendar on step-derived dates) | *Approx* (Approximated from temporal timeline offset) | Unavailable (No calendar date stamps) |
| 5 | `is_weekend` | Feature #5 | **Direct** (is_weekend = 1 if ((step // 24) % 7) >= 5 else 0) | **Direct** (is_weekend = 1 if ((TransactionDT // 86400) % 7) in [5, 6] else 0) | Unavailable (No day timestamps) |
| 6 | `amount_vs_avg_ratio` | Feature #6 | **Direct** (Calculable from rolling historical mean of nameOrig using past transactions only) | **Direct** (Calculable per card1+addr1 pseudo-account entity rolling historical mean) | *Approx* (Proxy via proposed_credit_limit vs income) |
| 7 | `amount_vs_std_zscore` | Feature #7 | **Direct** (Calculable from rolling historical std of nameOrig using past transactions only) | **Direct** (Calculable per card1+addr1 pseudo-account entity rolling historical std) | *Approx* (Z-score of proposed credit limit normalized against income band) |
| 8 | `txn_count_last_hour` | Feature #8 | **Direct** (Count of transactions for nameOrig in step window [step - 1, step)) | **Direct** (Count of transactions for card1+addr1 in [TransactionDT - 3600, TransactionDT)) | **Direct** (Direct column 'velocity_6h' / 'velocity_24h' proxy) |
| 9 | `txn_count_last_24h` | Feature #9 | **Direct** (Count of transactions for nameOrig in step window [step - 24, step)) | **Direct** (Count of transactions for card1+addr1 in [TransactionDT - 86400, TransactionDT)) | **Direct** (Direct column 'velocity_24h') |
| 10 | `new_payee_flag` | Feature #10 | **Direct** (1 if nameDest has not been previously seen for nameOrig, else 0) | *Approx* (Proxy via recipient domain P_emaildomain / R_emaildomain match or merchant identity) | Unavailable (Account opening / application dataset, not transaction graph) |
| 11 | `new_payee_pct_last_7days` | Feature #11 | **Direct** (Fraction of payees in past 7 days (168 steps) that were first-time interactions) | *Approx* (Ratio of new recipient domains or merchant targets over rolling 7-day window) | Unavailable (No payee entities) |
| 12 | `days_since_account_created` | Feature #12 | *Approx* (Approximate proxy from earliest observed step for nameOrig) | *Approx* (Proxy via D1 feature (days since account/card registration)) | **Direct** (Direct column 'customer_age' / bank branch tenure) |
| 13 | `known_device_flag` | Feature #13 | Unavailable (PaySim contains no device ID, IP, or user-agent hardware metadata) | **Direct** (Mapped via train_identity.csv DeviceType, DeviceInfo, id_30, id_31) | **Direct** (Direct column 'device_os' and 'device_distinct_emails_8w') |
| 14 | `device_change_count_30days` | Feature #14 | Unavailable (No device tracking in PaySim schema) | **Direct** (Count of distinct DeviceInfo or id_31 per card1+addr1 over 30 days) | **Direct** (Direct column 'device_distinct_emails_8w' proxy) |
| 15 | `payee_incoming_txn_count` | Feature #15 | **Direct** (In-degree / transaction volume received by nameDest over past time window) | *Approx* (Aggregated volume per merchant / R_emaildomain target) | Unavailable (No destination payee data) |
| 16 | `payee_account_age_days` | Feature #16 | *Approx* (Step of earliest received/sent transaction for nameDest) | Unavailable (Merchant registration inception date not in IEEE-CIS schema) | Unavailable (No destination payee data) |
| 17 | `is_scam_upi` | Feature #17 | Unavailable (No external scam blacklist in PaySim) | Unavailable (No external scam blacklist mapping) | Unavailable (No scam UPI directory) |
| 18 | `distance_from_home_km` | Feature #18 | Unavailable (PaySim contains no geolocation (GPS/IP) coordinates) | *Approx* (addr1 / addr2 geographic region distance divergence) | Unavailable (No lat/lon GPS coordinates) |
| 19 | `is_impossible_travel` | Feature #19 | Unavailable (No geographic coordinates or location velocity available) | *Approx* (addr1 state jump within < 2 hours) | Unavailable (No geolocation tracking) |
| 20 | `payee_graph_centrality` | Feature #20 | **Direct** (Real transaction graph constructed from nameOrig -> nameDest directed edges) | *Approx* (Bipartite graph between card1 and R_emaildomain / merchant cluster) | Unavailable (No network topology) |
| 21 | `is_mule_candidate` | Feature #21 | **Direct** (High fan-in (many distinct senders) followed by rapid disbursement (fan-out)) | Unavailable (Card-not-present acquiring dataset; does not trace multi-hop receiver payouts) | *Approx* (Proxy via phone_home_valid, phone_mobile_valid, foreign_request indicators) |
| 22 | `is_high_risk_mcc` | Feature #22 | Unavailable (PaySim provides transaction type (TRANSFER, CASH_OUT, PAYMENT) but no ISO 18245 MCC) | *Approx* (ProductCD / M1-M9 flags and category groupings) | Unavailable (Application dataset; no merchant MCC) |

## 5. Forensic Analysis: Synthetic Gaussian Overlays in `backend/data_processor.py`
### 5.1 The Defect
In `backend/data_processor.py` (lines 142–230), the feature engineering routine previously attempted to augment raw transaction datasets by synthetically generating 18 operational features.
Critically, the generator branched directly on the ground truth target label:
```python
# Line 151 in backend/data_processor.py
fraud_mask = merged_df['is_fraud'] == 1

# Line 154-155: Amount vs std z-score
z_scores = np.random.normal(loc=0.5, scale=0.8, size=n_rows)
z_scores[fraud_mask] = np.random.normal(loc=4.5, scale=1.5, size=sum(fraud_mask))

# Line 159-160: Amount vs average ratio
ratios = np.random.normal(loc=1.1, scale=0.4, size=n_rows)
ratios[fraud_mask] = np.random.normal(loc=6.0, scale=3.0, size=sum(fraud_mask))

# Line 164-165: Transaction count last hour
v_hour = np.random.choice([1, 2, 3, 4], p=[0.8, 0.15, 0.04, 0.01], size=n_rows)
v_hour[fraud_mask] = np.random.choice([2, 5, 8, 12], p=[0.1, 0.3, 0.4, 0.2], size=sum(fraud_mask))

# Line 209-210: Distance from home (km)
dist = np.random.uniform(0.1, 20.0, size=n_rows)
dist[fraud_mask] = np.random.uniform(100.0, 1500.0, size=sum(fraud_mask))

# Line 213-214: Impossible travel
imp_travel = np.random.choice([0, 1], p=[0.99, 0.01], size=n_rows)
imp_travel[fraud_mask] = np.random.choice([0, 1], p=[0.3, 0.7], size=sum(fraud_mask))
```

### 5.2 Why This Constitutes Direct Target Label Leakage
1. **Complete Separability**: For `distance_from_home_km`, legitimate transactions are bounded in `[0.1, 20.0]` while fraudulent transactions are bounded in `[100.0, 1500.0]`. The intersection is the empty set ($\emptyset$). Any decision tree or neural network splits on `distance_from_home_km > 20.0` and achieves 100% precision and 100% recall with zero error.
2. **Bypassing Genuine Data Signals**: The models trained on this synthetic overlay did not learn real financial crime behaviors; they memorized the parameter distributions (`loc=4.5, scale=1.5` vs `loc=0.5, scale=0.8`) of NumPy's pseudo-random number generator.
3. **Disastrous Production Drift**: When deployed to live production, real fraud does not arrive labeled with Gaussian distributions. Real UPI attackers often use low-and-slow transactions within normal geofences, resulting in catastrophic model failure.
4. **Violation of Causal Ordering**: Future target information (`is_fraud`) was used to construct historical and present feature values, violating fundamental temporal causality.

### 5.3 Honest Solution Architecture (Parts 18–21)
1. **Part 18 (`data_loader.py`)**: Chunked loaders derive genuine historical features using *only past transactions* (no future leakage). PaySim builds a real NetworkX/graph structure over `nameOrig` -> `nameDest`; IEEE-CIS groups by `card1+addr1` over historical timestamps (`TransactionDT`).
2. **Part 19 (`feature_builder.py`)**: Unified canonical feature extractor shared symmetrically by training and production runtime (`/api/transfer`, `/api/predict_secure`).
3. **Part 20 (`upi_simulator.py`)**: Generates realistic UPI behavior patterns with overlapping feature distributions, hard legitimate boundary cases (large rent, travel, festival spikes), low-and-slow fraud, 0.5% label noise, natural fraud rates (2–5%), strictly ensuring every single-feature AUC is below 0.9.
4. **Part 21 (`train_all_models.py`)**: Strict chronological time-based train (70%) / validation (15%) / test (15%) split, fitting the `StandardScaler` on the training split only, and evaluating on raw un-resampled holdouts.

## 6. Tier 3 Non-Tabular Artifacts
- `0ANNUALREPORT202324_FULLDF549205FA214F62A2441C5320D64A29.pdf` (7.4 MB): Reserve Bank of India / NPCI Annual Report detailing macro payments ecosystem risk metrics, fraud volume trends, and regulatory guidelines.
- `Ecosystem-Statistics-UPI-Chargeback-2025-Aug.xlsx` through `2026-Jan.xlsx`: Monthly NPCI UPI ecosystem chargeback ratios, volume distributions, and settlement turnaround times, used for establishing baseline prior probabilities.