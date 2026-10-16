"""Six diagnostic scores with the original missing-score convention."""

from ..core import compute_paper_scores


def score_output(output, record):
    # A missing metric record remains missing; available-case denominators are
    # distinct from an optional missing-as-failure sensitivity analysis.
    if output is None:
        return None
    return compute_paper_scores(
        output, record["reference"], record["input"]["userInstruction"]
    )
