"""Inspect and safely backfill customer demo-domain eligibility reservations.

Run without --apply first. Ambiguous historical duplicates are reserved for manual
review and are never merged, deleted, or assigned to a replacement workspace.
"""

import argparse
from collections import defaultdict

from database import SessionLocal
from saas import models, service


PUBLIC_EMAIL_DOMAINS = {
    "gmail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
}


def _candidate_domain(organization, account) -> str:
    for value in (
        getattr(organization, "primary_domain", ""),
        getattr(organization, "website", ""),
    ):
        domain = service.normalize_organization_domain(value)
        if domain:
            return domain
    email_domain = service.normalize_organization_domain(getattr(account, "email", ""))
    return "" if email_domain in PUBLIC_EMAIL_DOMAINS else email_domain


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose customer demo-domain eligibility")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist safe normalized values and domain reservations after reviewing this report.",
    )
    args = parser.parse_args()
    db = SessionLocal()
    try:
        rows = (
            db.query(models.SaaSDemoRequest, models.PendingOrganization, models.SaaSAccount)
            .join(
                models.PendingOrganization,
                models.PendingOrganization.id == models.SaaSDemoRequest.pending_organization_id,
            )
            .join(
                models.SaaSAccount,
                models.SaaSAccount.id == models.SaaSDemoRequest.requester_saas_account_id,
            )
            .filter(models.SaaSDemoRequest.workspace_classification_snapshot == "customer_demo")
            .all()
        )
        by_domain: dict[str, list[object]] = defaultdict(list)
        unresolved = 0
        for request_row, organization, account in rows:
            domain = _candidate_domain(organization, account)
            if not domain:
                unresolved += 1
                continue
            by_domain[domain].append(request_row)

        duplicate_domains = {
            domain: requests for domain, requests in by_domain.items() if len(requests) > 1
        }
        print(f"customer_demo_requests={len(rows)}")
        print(f"normalized_domains={len(by_domain)}")
        print(f"unresolved_domains={unresolved}")
        print(f"manual_review_duplicate_domains={len(duplicate_domains)}")
        for domain, requests in sorted(duplicate_domains.items()):
            print(f"manual_review domain={domain} request_count={len(requests)}")

        if not args.apply:
            print("dry_run=true")
            return 0

        for domain, requests in by_domain.items():
            for request_row in requests:
                request_row.organization_domain_normalized = domain
            eligibility = db.query(models.SaaSDemoDomainEligibility).filter_by(
                normalized_domain=domain
            ).first()
            if eligibility:
                continue
            if len(requests) == 1:
                db.add(
                    models.SaaSDemoDomainEligibility(
                        normalized_domain=domain,
                        demo_request_id=requests[0].id,
                        status="reserved",
                    )
                )
            else:
                db.add(
                    models.SaaSDemoDomainEligibility(
                        normalized_domain=domain,
                        status="manual_review",
                        manual_review_reason=(
                            "Multiple historical customer demo requests share this organization domain."
                        ),
                    )
                )
        db.commit()
        print("apply_complete=true")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
