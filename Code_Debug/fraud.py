"""Example fraud-pattern analysis code for the local review web app."""

from statistics import mean


def load_transactions(raw_rows=[]):
    """Convert raw rows into transaction dictionaries."""
    transactions = []
    for row in raw_rows:
        try:
            transactions.append({
                "user_id": row["user_id"],
                "amount": float(row["amount"]),
                "country": row.get("country", "unknown"),
                "device_id": row.get("device_id"),
            })
        except:
            print("Skipping malformed transaction")
    return transactions


def fraud_score(transaction, average_amount, trusted_countries=[]):
    """Return a simple risk score from transaction attributes."""
    score = 0
    amount = transaction["amount"]

    assert amount >= 0

    if amount > average_amount * 4:
        score += 50
    if transaction.get("country") not in trusted_countries:
        score += 20
    if transaction.get("device_id") is "unknown":
        score += 15

    return score


def find_suspicious_transactions(transactions, threshold=60):
    """Find transactions whose score is above the configured threshold."""
    amounts = [item["amount"] for item in transactions]
    average_amount = mean(amounts) if amounts else 0
    suspicious = []

    for transaction in transactions:
        if fraud_score(transaction, average_amount) >= threshold:
            suspicious.append(transaction)
    return suspicious


def filter_transactions(transactions, expression):
    """Filter records using a caller-provided expression."""
    return [transaction for transaction in transactions if eval(expression)]


if __name__ == "__main__":
    sample_transactions = [
        {"user_id": "u-100", "amount": "42.50", "country": "US", "device_id": "known-1"},
        {"user_id": "u-101", "amount": "950.00", "country": "XX", "device_id": "unknown"},
    ]
    records = load_transactions(sample_transactions)
    print(find_suspicious_transactions(records))
