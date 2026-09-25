"""Generate submission.jsonl from the canonical expanded test pairs."""

import json
from pathlib import Path

from composer.composer import EngagementComposer


def main() -> None:
    root = Path(__file__).parent
    pairs = json.loads((root / "expanded" / "test_pairs.json").read_text(encoding="utf-8"))["pairs"]
    composer = EngagementComposer()
    lines = []
    fallbacks = 0

    for pair in pairs:
        merchant = json.loads((root / "expanded" / "merchants" / f"{pair['merchant_id']}.json").read_text(encoding="utf-8"))
        trigger = json.loads((root / "expanded" / "triggers" / f"{pair['trigger_id']}.json").read_text(encoding="utf-8"))
        category = json.loads((root / "expanded" / "categories" / f"{merchant['category_slug']}.json").read_text(encoding="utf-8"))
        customer = None
        if pair.get("customer_id"):
            customer = json.loads((root / "expanded" / "customers" / f"{pair['customer_id']}.json").read_text(encoding="utf-8"))

        message = composer.compose(category, merchant, trigger, customer=customer)
        fallbacks += int(message.is_fallback)
        lines.append(json.dumps({
            "test_id": pair["test_id"],
            "body": message.body,
            "cta": message.cta,
            "send_as": message.send_as,
            "suppression_key": trigger.get("suppression_key"),
            "rationale": message.rationale,
        }, ensure_ascii=False))

    (root / "submission.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"generated={len(lines)} fallbacks={fallbacks}")


if __name__ == "__main__":
    main()