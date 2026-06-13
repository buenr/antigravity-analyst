import os
import unittest


os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("GCS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from app.routers.chat import (  # noqa: E402
    ANALYST_BRIEF_PROMPT,
    build_data_science_prompt,
    parse_analysis_contract,
)


class ChatPromptTests(unittest.TestCase):
    def test_data_science_prompt_embeds_request_and_business_requirements(self):
        user_request = "Find the main revenue drivers by segment."

        prompt = build_data_science_prompt(user_request)

        self.assertIn(user_request, prompt)
        self.assertIn("business analyst", prompt)
        self.assertIn("apparent business grain", prompt)
        self.assertIn("missing values, duplicates, suspicious values, outliers", prompt)
        self.assertIn("practical significance", prompt)
        self.assertIn("simple baseline", prompt)
        self.assertIn("choose the right chart type", prompt)
        self.assertIn("start bar charts at zero", prompt)
        self.assertIn("avoid misleading scales or clutter", prompt)
        self.assertIn('explain the business impact', prompt)
        self.assertIn("./outputs/", prompt)

    def test_analyst_brief_prompt_includes_business_readiness_guidance(self):
        self.assertIn("KPI candidates", ANALYST_BRIEF_PROMPT)
        self.assertIn("business grain", ANALYST_BRIEF_PROMPT)
        self.assertIn("Data-readiness risks", ANALYST_BRIEF_PROMPT)
        self.assertIn("Practical next analyses", ANALYST_BRIEF_PROMPT)

    def test_parse_analysis_contract_still_accepts_required_sections(self):
        text = """
Summary before the contract.

## Findings
- Revenue increased in the west segment.
## Assumptions
- Segment definitions are stable.
## Data Quality
- One column has missing values.
## Methods
- Grouped revenue by segment.
## Limitations
- No causal claim.
## Artifacts
- None
"""

        contract = parse_analysis_contract(text)

        self.assertTrue(contract.valid)
        self.assertEqual(contract.missing_sections, [])
        self.assertEqual(contract.findings, ["Revenue increased in the west segment."])
        self.assertEqual(contract.artifacts, [])


if __name__ == "__main__":
    unittest.main()
