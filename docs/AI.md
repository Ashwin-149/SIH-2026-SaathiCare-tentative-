# AI and Risk Methodology

## Dynamic distress score

The prototype normalizes 11 self-report/context features to 0–100 and combines them with transparent weights. Safety and threat indicators receive higher weights because the problem context specifically includes intimidation and safety concerns.

The score is supplemented by a Random Forest trained on synthetic data. The ML probability is a supporting signal, not a clinical truth.

## Explainability

Each result stores factor-level scores and displays the top contributors. The dashboard also shows the difference from the user's recent personal baseline.

## Longitudinal trend

Recent check-in scores are compared with a rolling personal baseline. Trend labels are:
- IMPROVING
- STABLE
- FLUCTUATING
- WORSENING
- RAPIDLY WORSENING

## Limitations

Synthetic data is not representative of real victim populations. No clinical claims should be made from the model. Real deployment requires field validation, bias evaluation, security review, human factors testing and government approval.
