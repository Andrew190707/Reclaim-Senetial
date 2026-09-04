# Evaluation

Metrics are computed at startup from the generated held-out test set and exposed live at `/api/evaluation` and in the Model Evaluation page. They are never hardcoded in the dashboard.

The locked classifier threshold is 0.35. The page reports precision, recall, F1, ROC-AUC, PR-AUC, confusion matrix, false-positive and false-negative counts, explicit false-positive cost, fraudulent refund amount detected, legitimate value incorrectly held, and a threshold trade-off table.

The business impact calculation is:

```text
fraudulent refunds prevented = sum(refund_amount for detected fraudulent test cases)
legitimate value held = sum(refund_amount for false-positive test cases)
net protected merchant value = prevented - legitimate value held
```

The default false-positive cost assumption is ₹180 per case and is shown alongside the actual incorrectly held value. This is a prototype assumption, not an accounting claim.
