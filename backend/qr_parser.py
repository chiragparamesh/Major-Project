from urllib.parse import urlparse, parse_qs
import logging

logger = logging.getLogger(__name__)

# List of blacklisted merchant names (simulated or known malicious merchants)
BLACKLISTED_MERCHANTS = [
    "lottery win prize",
    "free gift card merchant",
    "rewards processing hub",
    "fast crypto double",
    "fake support support",
    "loan processing instant"
]

def parse_upi_qr(qr_string: str) -> dict:
    """
    Parses a UPI URL or raw QR text and extracts payee address, payee name, amount, etc.
    Example URL: upi://pay?pa=receiver@bank&pn=Merchant%20Name&am=1000&cu=INR&tn=Payment%20note
    """
    if not qr_string or not qr_string.startswith("upi://"):
        logger.warning(f"Invalid UPI scheme received: {qr_string}")
        return {
            'pa': '',
            'pn': '',
            'am': '0',
            'cu': 'INR',
            'tn': ''
        }
        
    try:
        parsed = urlparse(qr_string)
        params = parse_qs(parsed.query)
        
        return {
            'pa': params.get('pa', [''])[0],
            'pn': params.get('pn', [''])[0],
            'am': params.get('am', ['0'])[0],
            'cu': params.get('cu', ['INR'])[0],
            'tn': params.get('tn', [''])[0],
        }
    except Exception as e:
        logger.error(f"Failed to parse UPI QR code string: {e}")
        return {
            'pa': '',
            'pn': '',
            'am': '0',
            'cu': 'INR',
            'tn': ''
        }

def is_blacklisted_merchant(merchant_name: str) -> bool:
    """Checks if a merchant name is blacklisted or contains blacklisted terms"""
    if not merchant_name:
        return False
    name_lower = merchant_name.lower()
    return any(merchant in name_lower for merchant in BLACKLISTED_MERCHANTS)

def validate_qr(qr_data: dict, entered_upi: str, entered_amount: float) -> tuple:
    """
    Perform 4 key security checks on the QR data:
    1. QR UPI address matches entered UPI address (tampering check)
    2. QR amount matches entered amount (if QR encodes an amount)
    3. Merchant name blacklist check
    4. Suspicious keyword search in payment note
    """
    flags = []
    score = 0
    
    if not qr_data or not qr_data.get('pa'):
        return 0, []
        
    # Check 1: UPI ID mismatch (most critical - indicates sticker/rendering swap)
    if qr_data['pa'].strip().lower() != entered_upi.strip().lower():
        score += 80
        flags.append("QR UPI does not match entered UPI — possible sticker overlay or injection tampering")
        
    # Check 2: Amount mismatch
    # Note: If QR amount is 0 or empty, it means user enters amount manually, which is not a mismatch.
    qr_amount = qr_data.get('am')
    if qr_amount:
        try:
            # float() must stay inside the try: a QR with "am=abc" used to raise a 500.
            if float(qr_amount) > 0 and abs(float(qr_amount) - float(entered_amount)) > 0.01:
                score += 30
                flags.append(f"QR encoded amount (₹{qr_amount}) does not match entered amount (₹{entered_amount})")
        except (ValueError, TypeError):
            score += 30
            flags.append("QR encoded amount is not a valid number")
            
    # Check 3: Blacklisted merchant name
    merchant_name = qr_data.get('pn', '')
    if is_blacklisted_merchant(merchant_name):
        score += 65
        flags.append(f"Merchant is on local blacklist: {merchant_name}")
        
    # Check 4: Suspicious keywords in note
    note = qr_data.get('tn', '')
    if note:
        suspicious_words = ['otp', 'urgent', 'prize', 'verify', 'kyc', 'block', 'expired', 'lottery', 'double', 'refund']
        note_lower = note.lower()
        matched_words = [word for word in suspicious_words if word in note_lower]
        if matched_words:
            score += 30
            flags.append(f"Suspicious keywords in QR payment note: {note} (matched: {', '.join(matched_words)})")
            
    return score, flags
