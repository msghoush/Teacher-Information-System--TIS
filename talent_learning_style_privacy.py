"""Owner-approved boundary between operational rows and aggregate disclosures.

Learning Style ordinarily retains the M14 aggregate exception. A Classification
filter makes its denominator a sensitive Classification disclosure. The selected
band cell and its scope total must be visible after the existing primary and
complementary policy, or no Learning Style numbers are serialized.
This helper has no effect on individually authorized Student rows.
"""
from student_learning_style_analytics import build_distribution


def classification_cohort_publishable(projection, classification):
    if not classification:
        return True
    if not projection or projection.get("state") != "visible":
        return False
    if projection.get("total", {}).get("state") != "visible":
        return False
    bucket = next((b for b in projection.get("buckets", []) if b.get("label") == classification), None)
    return bool(bucket and bucket.get("state") == "visible" and bucket.get("count") is not None)


def learning_style_projection(students, *, classification=None, classification_projection=None,
                              filtered_classification_projection=None):
    safe = classification_cohort_publishable(classification_projection, classification)
    if filtered_classification_projection is not None:
        safe = safe and classification_cohort_publishable(filtered_classification_projection, classification)
    if not safe:
        return {
            "state": "restricted",
            "reason_code": "classification_cohort_protected",
            "total": {"state": "restricted", "value": None},
            "total_population": None,
            "levels": [],
        }
    return build_distribution(students)
