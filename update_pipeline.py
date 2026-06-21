import re

with open("src/etl/pipeline.py", "r") as f:
    content = f.read()

# Replace matched_results assignments to include final_care_type
content = content.replace(
    'matched_results[(payroll_name, care_type)] = (0.0, 0.0, None, match_status, None)',
    'matched_results[(payroll_name, care_type)] = (0.0, 0.0, None, match_status, None, care_type)'
)

content = content.replace(
    'matched_results[(payroll_name, care_type)] = (billed_hrs, paid_hrs, remit_insurance, match_status, remit_name)',
    'matched_results[(payroll_name, care_type)] = (billed_hrs, paid_hrs, remit_insurance, match_status, remit_name, care_type)'
)

content = content.replace(
    'matched_results[(payroll_name, care_type)] = (0.0, 0.0, None, "UNMATCHED", None)',
    'matched_results[(payroll_name, care_type)] = (0.0, 0.0, None, "UNMATCHED", None, care_type)'
)

# For the fallback case, we use the remittance care_type which is fallback_key[1]
content = content.replace(
    'matched_results[(payroll_name, care_type)] = (billed_hrs, paid_hrs, remit_insurance, match_status, remit_name, care_type)\n                        log.debug(\n                            "Care type fallback used for %s: payroll=%s, remit care_type differs",',
    'matched_results[(payroll_name, care_type)] = (billed_hrs, paid_hrs, remit_insurance, match_status, remit_name, fallback_key[1])\n                        log.debug(\n                            "Care type fallback used for %s: payroll=%s, remit care_type differs",'
)

content = content.replace(
    'matched_results[(payroll_name, care_type)] = (0.0, 0.0, None, match_status, remit_name)',
    'matched_results[(payroll_name, care_type)] = (0.0, 0.0, None, match_status, remit_name, care_type)'
)

content = content.replace(
    'billed_hrs, paid_hrs, remit_insurance, match_status, remit_name = matched_results[(payroll_name, care_type)]',
    'billed_hrs, paid_hrs, remit_insurance, match_status, remit_name, final_care_type = matched_results[(payroll_name, care_type)]'
)

content = re.sub(
    r'"care_type": care_type,(\s*})\s*# Step 2',
    r'"care_type": final_care_type,\1# Step 2',
    content
)

with open("src/etl/pipeline.py", "w") as f:
    f.write(content)

