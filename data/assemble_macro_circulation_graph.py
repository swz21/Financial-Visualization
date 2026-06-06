#!/usr/bin/env python3
"""
Assemble an actor-centered macro-circulation graph JSON for D3.

Inputs:
  - fof_nonfinancial_sector_tree_2023.json
  - fof_financial_sector_tree_2023.json

Output:
  - macro_circulation_graph_2023.json

Design goals:
  1) Keep editable/story material separate from calculated data.
  2) Precompute node metrics, edge values, ratios, and red-blood-cell diagnostics.
  3) Keep D3 simple: render the merged `graph.nodes`, `graph.edges`, and `scenes`.

Important modeling note:
  This is a simplified sectoral macro-accounting circulation model. It is not
  literal transaction-level tracking of individual yuan. Some edges use official
  values but simplified counterparties for teaching clarity; those edges are
  marked with `evidence_level`.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

Number = Optional[float]

# ---------------------------------------------------------------------------
# Editable / manual layer
# ---------------------------------------------------------------------------
# Your team should feel free to tweak labels, explanatory copy, layouts, scenes,
# visual hints, and default visibility here. The calculated layer below will
# recompute numeric values and ratios from the official tree JSON files.

MANUAL_SPEC: Dict[str, Any] = {
    "metadata": {
        "title": "China Macro Circulation Model, 2023",
        "subtitle": "An actor-centered flow-of-funds graph for the red-blood-cell metaphor",
        "year": 2023,
        "unit": "亿元",
        "model_type": "actor_centered_circulation_graph",
        "node_rule": "Nodes are economic actors or process nodes.",
        "edge_rule": "Edges are economic relationships: payments, taxes, transfers, deposits, loans, bonds, and investment flows.",
        "important_caveat": "This graph shows sectoral macro-accounting flows, not literal transaction-level money paths.",
    },
    "nodes": [
        {
            "id": "households",
            "label": "Households",
            "label_cn": "住户部门",
            "node_type": "actor",
            "actor_type": "institutional_sector",
            "is_money_holder": True,
            "zone": "domestic_real_economy",
            "layout": {"x": 0.16, "y": 0.48},
            "short_explanation": "People and families: receive income, consume, save, deposit, and borrow.",
            "visual_hints": {
                "size_metric": "adjusted_disposable_income",
                "ring_metric": "clotting_score",
                "color_role": "household",
                "badge_metrics": ["actual_final_consumption", "gross_saving", "deposits"],
            },
        },
        {
            "id": "firms",
            "label": "Firms / Producers",
            "label_cn": "非金融企业 / 生产者",
            "node_type": "actor",
            "actor_type": "institutional_sector",
            "is_money_holder": True,
            "zone": "domestic_real_economy",
            "layout": {"x": 0.66, "y": 0.48},
            "short_explanation": "Nonfinancial firms: produce goods/services, pay wages and taxes, borrow, and invest.",
            "visual_hints": {
                "size_metric": "value_added",
                "ring_metric": "borrowing_pressure_score",
                "color_role": "firms",
                "badge_metrics": ["value_added", "compensation_paid", "gross_capital_formation"],
            },
        },
        {
            "id": "financial_institutions",
            "label": "Financial Institutions / Banks",
            "label_cn": "金融机构 / 银行等",
            "node_type": "actor",
            "actor_type": "institutional_sector",
            "is_money_holder": True,
            "zone": "financial_system",
            "layout": {"x": 0.38, "y": 0.78},
            "short_explanation": "The financial transformer: receives deposits and other liabilities, acquires loans and securities as assets.",
            "visual_hints": {
                "size_metric": "financial_uses_total",
                "ring_metric": "recirculation_score",
                "color_role": "finance",
                "badge_metrics": ["deposit_liabilities", "loan_assets", "debt_security_assets"],
            },
        },
        {
            "id": "government",
            "label": "Government",
            "label_cn": "广义政府",
            "node_type": "actor",
            "actor_type": "institutional_sector",
            "is_money_holder": True,
            "zone": "fiscal_system",
            "layout": {"x": 0.46, "y": 0.17},
            "short_explanation": "The fiscal valve: taxes, transfers, public consumption, public investment, and bond financing.",
            "visual_hints": {
                "size_metric": "disposable_income",
                "ring_metric": "borrowing_pressure_score",
                "color_role": "government",
                "badge_metrics": ["actual_final_consumption", "gross_capital_formation", "debt_security_liabilities"],
            },
        },
        {
            "id": "rest_of_world",
            "label": "Rest of World",
            "label_cn": "国外部门",
            "node_type": "actor",
            "actor_type": "external_sector",
            "is_money_holder": True,
            "zone": "external",
            "layout": {"x": 0.89, "y": 0.36},
            "short_explanation": "External demand and cross-border income/financial flows.",
            "visual_hints": {
                "size_metric": "net_exports_display_value",
                "ring_metric": "external_oxygen_score",
                "color_role": "external",
                "badge_metrics": ["net_exports_display_value", "property_income_received_from_domestic"],
            },
        },
        {
            "id": "production_engine",
            "label": "Production Engine",
            "label_cn": "生产引擎",
            "node_type": "process",
            "actor_type": None,
            "is_money_holder": False,
            "zone": "process",
            "layout": {"x": 0.77, "y": 0.68},
            "short_explanation": "Not a wallet: a process that turns labor, capital, and demand into future income.",
            "visual_hints": {
                "size_metric": "domestic_value_added",
                "ring_metric": "investment_intensity",
                "color_role": "production",
                "badge_metrics": ["domestic_value_added", "gross_capital_formation"],
            },
        },
    ],
    "edge_categories": {
        "labor_income": "Wages and compensation of employees.",
        "goods_and_services": "Consumption, public consumption, and external demand.",
        "fiscal": "Taxes, social contributions, transfers, subsidies, and public redistribution.",
        "saving_and_deposits": "Deposits, insurance reserves, and financial saving flows.",
        "credit": "Loans and other credit flows.",
        "securities": "Bond financing and other debt securities.",
        "investment": "Capital formation and productive investment channels.",
        "external": "Cross-border demand and income flows.",
        "conceptual": "Dashed explanatory links, not directly measured official flows.",
    },
    "glossary": {
        "compensation_of_employees": {
            "label": "Compensation of employees",
            "label_cn": "劳动者报酬",
            "plain_english": "Wages and labor income paid to workers.",
            "why_it_matters": "One of the main ways production becomes household income.",
        },
        "actual_final_consumption": {
            "label": "Actual final consumption",
            "label_cn": "实际最终消费",
            "plain_english": "Goods and services actually consumed by households or government.",
            "why_it_matters": "The main oxygen-delivery path in the red-blood-cell metaphor.",
        },
        "gross_saving": {
            "label": "Gross saving",
            "label_cn": "总储蓄",
            "plain_english": "Income not used for current consumption after relevant accounting adjustments.",
            "why_it_matters": "High saving can fund investment, but can also signal weak consumption circulation.",
        },
        "deposits": {
            "label": "Deposits",
            "label_cn": "存款",
            "plain_english": "Money placed in bank-like accounts.",
            "why_it_matters": "Deposits are safe storage; large deposit accumulation can represent clotting.",
        },
        "loans": {
            "label": "Loans",
            "label_cn": "贷款",
            "plain_english": "Borrowed funds: liabilities for borrowers and assets for lenders.",
            "why_it_matters": "Loans recirculate saved money into households, firms, and government.",
        },
        "debt_securities": {
            "label": "Debt securities / bonds",
            "label_cn": "债券",
            "plain_english": "Borrowing through bond issuance rather than direct loans.",
            "why_it_matters": "In this graph, government financing is heavily bond-based.",
        },
        "net_exports": {
            "label": "Net exports",
            "label_cn": "净出口",
            "plain_english": "Exports minus imports. In the money-flow view, positive net export demand is drawn as payment from the rest of the world into domestic producers.",
            "why_it_matters": "It shows the external-demand pipe in the circulation model.",
        },
        "net_financial_investment": {
            "label": "Net financial investment",
            "label_cn": "净金融投资",
            "plain_english": "Positive means net lending/surplus; negative means net borrowing/financing need.",
            "why_it_matters": "A compact way to show which sectors supply funds and which need financing.",
        },
    },
    "scenes": [
        {
            "id": "domestic_demand_loop",
            "title": "1. Domestic demand loop",
            "description": "Firms pay income to households; households return demand through consumption.",
            "active_nodes": ["households", "firms"],
            "active_edges": ["firms_to_households_wages", "households_to_firms_consumption"],
        },
        {
            "id": "savings_and_clotting",
            "title": "2. Savings and clotting",
            "description": "A large household flow enters deposits and insurance reserves rather than immediately returning as consumption.",
            "active_nodes": ["households", "financial_institutions"],
            "active_edges": ["households_to_financial_deposits", "households_to_financial_insurance"],
        },
        {
            "id": "credit_recirculation",
            "title": "3. Credit recirculation",
            "description": "The financial system channels funds into loans and bonds for firms, households, and government.",
            "active_nodes": ["financial_institutions", "firms", "government", "households"],
            "active_edges": ["financial_to_firms_loans", "financial_to_households_loans", "financial_to_government_bonds"],
        },
        {
            "id": "fiscal_valve",
            "title": "4. Government as fiscal valve",
            "description": "Taxes and contributions enter government; transfers and public spending flow back out.",
            "active_nodes": ["government", "households", "firms"],
            "active_edges": ["households_to_government_current_transfers", "firms_to_government_production_taxes", "government_to_households_current_transfers", "government_to_firms_public_consumption"],
        },
        {
            "id": "external_demand",
            "title": "5. External demand",
            "description": "The rest of the world supplies demand through net exports. Goods flow outward; payment/demand flows inward.",
            "active_nodes": ["rest_of_world", "firms"],
            "active_edges": ["rest_world_to_firms_net_exports"],
        },
        {
            "id": "investment_loop",
            "title": "6. Investment and future income",
            "description": "Investment is not a dead end. It may create future production and income, but its return quality is not proven by this flow table.",
            "active_nodes": ["firms", "government", "households", "production_engine"],
            "active_edges": ["firms_to_production_investment", "government_to_production_public_investment", "households_to_production_capital_formation", "production_to_households_future_income"],
        },
        {
            "id": "red_blood_cell_diagnosis",
            "title": "7. Red blood cell diagnosis",
            "description": "Healthy oxygen delivery, clotting, recirculation, debt dependence, and external oxygen are highlighted together.",
            "active_nodes": ["households", "firms", "financial_institutions", "government", "rest_of_world", "production_engine"],
            "active_edges": "all_measured_default_visible",
        },
    ],
}

# Edge specs are still partly manual because they define teaching direction,
# labels, and interpretations. Numeric values are calculated from extract rules.
EDGE_SPECS: List[Dict[str, Any]] = [
    # Labor income
    {
        "id": "firms_to_households_wages",
        "source": "firms",
        "target": "households",
        "label": "Wages from firms",
        "label_cn": "企业支付工资",
        "accounting_term": "Compensation of employees",
        "accounting_term_cn": "劳动者报酬",
        "category": "labor_income",
        "metaphor_role": "income_creation",
        "evidence_level": "direct_official_flow",
        "extract": {"table": "nf", "sector": "non_financial_enterprises", "side": "uses", "summary_key": "compensation_of_employees", "summary_side": "uses"},
        "plain_english": "Firms pay labor income to households. This is a main pipe from production to household purchasing power.",
        "jargon": "Recorded as compensation of employees paid by nonfinancial enterprises.",
        "default_visible": True,
    },
    {
        "id": "financial_to_households_wages",
        "source": "financial_institutions",
        "target": "households",
        "label": "Finance-sector wages",
        "label_cn": "金融部门工资",
        "accounting_term": "Compensation of employees",
        "accounting_term_cn": "劳动者报酬",
        "category": "labor_income",
        "metaphor_role": "income_creation",
        "evidence_level": "direct_official_flow",
        "extract": {"table": "nf", "sector": "financial_institutions", "side": "uses", "summary_key": "compensation_of_employees", "summary_side": "uses"},
        "plain_english": "Financial institutions also pay workers, adding to household income.",
        "jargon": "Recorded as compensation of employees paid by financial institutions.",
        "default_visible": False,
    },
    {
        "id": "government_to_households_wages",
        "source": "government",
        "target": "households",
        "label": "Public-sector wages",
        "label_cn": "公共部门工资",
        "accounting_term": "Compensation of employees",
        "accounting_term_cn": "劳动者报酬",
        "category": "labor_income",
        "metaphor_role": "income_creation",
        "evidence_level": "direct_official_flow",
        "extract": {"table": "nf", "sector": "genaral_governments", "side": "uses", "summary_key": "compensation_of_employees", "summary_side": "uses"},
        "plain_english": "Government pays wages to public-sector workers, moving public funds into household income.",
        "jargon": "Recorded as compensation of employees paid by general government.",
        "default_visible": True,
    },

    # Goods/services and external demand
    {
        "id": "households_to_firms_consumption",
        "source": "households",
        "target": "firms",
        "label": "Household consumption",
        "label_cn": "居民消费支出",
        "accounting_term": "Actual final consumption",
        "accounting_term_cn": "实际最终消费",
        "category": "goods_and_services",
        "metaphor_role": "oxygen_delivery",
        "evidence_level": "direct_official_flow_simplified_counterparty",
        "extract": {"table": "nf", "sector": "households", "side": "uses", "item_label": "实际最终消费"},
        "plain_english": "Households use income to buy goods and services. This is the main oxygen-delivery path for domestic demand.",
        "jargon": "The official value is household actual final consumption. It is drawn as Households → Firms for teaching clarity.",
        "caveat": "The table records a household use, not a literal counterparty matrix.",
        "default_visible": True,
    },
    {
        "id": "government_to_firms_public_consumption",
        "source": "government",
        "target": "firms",
        "label": "Public consumption / procurement",
        "label_cn": "政府消费 / 采购",
        "accounting_term": "Government actual final consumption",
        "accounting_term_cn": "政府实际最终消费",
        "category": "goods_and_services",
        "metaphor_role": "public_oxygen_delivery",
        "evidence_level": "direct_official_flow_simplified_counterparty",
        "extract": {"table": "nf", "sector": "genaral_governments", "side": "uses", "item_label": "实际最终消费"},
        "plain_english": "Government spending on final consumption supports demand for goods and services.",
        "jargon": "Recorded as government actual final consumption.",
        "caveat": "Drawn as Government → Firms for teaching clarity.",
        "default_visible": True,
    },
    {
        "id": "rest_world_to_firms_net_exports",
        "source": "rest_of_world",
        "target": "firms",
        "label": "Foreign demand / net exports",
        "label_cn": "外需 / 净出口",
        "accounting_term": "Net exports",
        "accounting_term_cn": "净出口",
        "category": "external",
        "metaphor_role": "external_oxygen",
        "evidence_level": "direct_official_flow_sign_normalized",
        "extract": {"table": "nf", "sector": "rest_of_the_world", "side": "sources", "item_label": "净出口", "transform": "abs"},
        "plain_english": "External demand enters the domestic circulation through net exports. Goods flow outward; payment/demand flows inward.",
        "jargon": "Net exports are exports minus imports. The graph uses absolute value and money-flow direction for teaching.",
        "caveat": "This is net exports, not gross exports; it is not a full export-dependence measure.",
        "default_visible": True,
    },

    # Fiscal
    {
        "id": "households_to_government_current_transfers",
        "source": "households",
        "target": "government",
        "label": "Taxes & social contributions",
        "label_cn": "税收与社保缴款",
        "accounting_term": "Current transfers paid by households",
        "accounting_term_cn": "住户经常转移支出",
        "category": "fiscal",
        "metaphor_role": "redistribution_valve_inflow",
        "evidence_level": "direct_official_flow_grouped",
        "extract": {"table": "nf", "sector": "households", "side": "uses", "item_label": "经常转移", "include_children": True},
        "plain_english": "Households send money into the fiscal/social system through taxes, social contributions, and other current transfers.",
        "jargon": "Grouped current transfers paid by households, including income/property taxes and social insurance contributions.",
        "default_visible": True,
    },
    {
        "id": "firms_to_government_production_taxes",
        "source": "firms",
        "target": "government",
        "label": "Production taxes",
        "label_cn": "生产税净额",
        "accounting_term": "Net taxes on production",
        "accounting_term_cn": "生产税净额",
        "category": "fiscal",
        "metaphor_role": "redistribution_valve_inflow",
        "evidence_level": "direct_official_flow",
        "extract": {"table": "nf", "sector": "non_financial_enterprises", "side": "uses", "item_label": "生产税净额"},
        "plain_english": "Firms pay net production taxes to government as part of the production process.",
        "jargon": "Recorded as net taxes on production paid by nonfinancial enterprises.",
        "default_visible": True,
    },
    {
        "id": "government_to_households_current_transfers",
        "source": "government",
        "target": "households",
        "label": "Social benefits & transfers",
        "label_cn": "社会福利与转移",
        "accounting_term": "Current transfers paid by government",
        "accounting_term_cn": "政府经常转移支出",
        "category": "fiscal",
        "metaphor_role": "redistribution_valve_outflow",
        "evidence_level": "direct_official_flow_simplified_counterparty",
        "extract": {"table": "nf", "sector": "genaral_governments", "side": "uses", "item_label": "经常转移", "include_children": True},
        "plain_english": "Government moves money back toward households through social benefits and transfers.",
        "jargon": "Recorded as current transfers paid by general government. Drawn toward households for teaching clarity.",
        "default_visible": True,
    },
    {
        "id": "government_to_households_social_transfers_in_kind",
        "source": "government",
        "target": "households",
        "label": "Services in kind",
        "label_cn": "实物社会转移",
        "accounting_term": "Social transfers in kind",
        "accounting_term_cn": "实物社会转移",
        "category": "fiscal",
        "metaphor_role": "public_service_delivery",
        "evidence_level": "direct_official_flow_non_cash_service",
        "extract": {"table": "nf", "sector": "genaral_governments", "side": "uses", "item_label": "实物社会转移"},
        "plain_english": "Government provides services to households, such as public services consumed by households even if not paid as cash.",
        "jargon": "Social transfers in kind are not ordinary cash payments; render separately or with a distinct style.",
        "default_visible": False,
    },

    # Saving and deposits
    {
        "id": "households_to_financial_deposits",
        "source": "households",
        "target": "financial_institutions",
        "label": "Deposits",
        "label_cn": "存款",
        "accounting_term": "Net acquisition of deposits",
        "accounting_term_cn": "存款资产增加",
        "category": "saving_and_deposits",
        "metaphor_role": "clotting",
        "evidence_level": "direct_official_flow",
        "extract": {"table": "fin", "sector": "households", "summary_key": "deposits", "summary_side": "uses"},
        "plain_english": "Households place a large share of new financial assets into deposits. This is the main clotting cue.",
        "jargon": "In the financial account, household deposits are net acquisition of deposit assets.",
        "default_visible": True,
    },
    {
        "id": "households_to_financial_insurance",
        "source": "households",
        "target": "financial_institutions",
        "label": "Insurance reserves",
        "label_cn": "保险准备金",
        "accounting_term": "Insurance technical reserves",
        "accounting_term_cn": "保险准备金",
        "category": "saving_and_deposits",
        "metaphor_role": "slow_saving_pool",
        "evidence_level": "direct_official_flow",
        "extract": {"table": "fin", "sector": "households", "summary_key": "insurance_reserves", "summary_side": "uses"},
        "plain_english": "Some household saving enters insurance-reserve-like financial claims.",
        "jargon": "Recorded as household net acquisition of insurance technical reserves.",
        "default_visible": True,
    },
    {
        "id": "firms_to_financial_deposits",
        "source": "firms",
        "target": "financial_institutions",
        "label": "Enterprise deposits",
        "label_cn": "企业存款",
        "accounting_term": "Net acquisition of deposits",
        "accounting_term_cn": "存款资产增加",
        "category": "saving_and_deposits",
        "metaphor_role": "storage_pool",
        "evidence_level": "direct_official_flow",
        "extract": {"table": "fin", "sector": "non_financial_corporations", "summary_key": "deposits", "summary_side": "uses"},
        "plain_english": "Firms also increase deposits, storing some money in the financial system.",
        "jargon": "Recorded as nonfinancial corporations' net acquisition of deposits.",
        "default_visible": False,
    },
    {
        "id": "government_to_financial_deposits",
        "source": "government",
        "target": "financial_institutions",
        "label": "Government deposits",
        "label_cn": "政府存款",
        "accounting_term": "Net acquisition of deposits",
        "accounting_term_cn": "存款资产增加",
        "category": "saving_and_deposits",
        "metaphor_role": "storage_pool",
        "evidence_level": "direct_official_flow",
        "extract": {"table": "fin", "sector": "general_government", "summary_key": "deposits", "summary_side": "uses"},
        "plain_english": "Government also holds/increases deposits, but in this flow view it is still a net borrower overall.",
        "jargon": "Recorded as general government net acquisition of deposits.",
        "default_visible": False,
    },

    # Credit and securities
    {
        "id": "financial_to_households_loans",
        "source": "financial_institutions",
        "target": "households",
        "label": "Household loans",
        "label_cn": "住户贷款",
        "accounting_term": "Net incurrence of loan liabilities",
        "accounting_term_cn": "贷款负债增加",
        "category": "credit",
        "metaphor_role": "credit_recirculation",
        "evidence_level": "direct_official_flow_simplified_lender",
        "extract": {"table": "fin", "sector": "households", "summary_key": "loans", "summary_side": "sources"},
        "plain_english": "Households borrow, receiving credit but also taking on liabilities.",
        "jargon": "Recorded as household net incurrence of loan liabilities. Drawn from the financial system for teaching clarity.",
        "default_visible": True,
    },
    {
        "id": "financial_to_firms_loans",
        "source": "financial_institutions",
        "target": "firms",
        "label": "Firm loans",
        "label_cn": "企业贷款",
        "accounting_term": "Net incurrence of loan liabilities",
        "accounting_term_cn": "贷款负债增加",
        "category": "credit",
        "metaphor_role": "credit_recirculation",
        "evidence_level": "direct_official_flow_simplified_lender",
        "extract": {"table": "fin", "sector": "non_financial_corporations", "summary_key": "loans", "summary_side": "sources"},
        "plain_english": "Firms rely heavily on loans to finance activity and investment.",
        "jargon": "Recorded as nonfinancial corporations' net incurrence of loan liabilities.",
        "default_visible": True,
    },
    {
        "id": "financial_to_government_loans",
        "source": "financial_institutions",
        "target": "government",
        "label": "Government loans",
        "label_cn": "政府贷款",
        "accounting_term": "Net incurrence of loan liabilities",
        "accounting_term_cn": "贷款负债增加",
        "category": "credit",
        "metaphor_role": "credit_recirculation",
        "evidence_level": "direct_official_flow_simplified_lender",
        "extract": {"table": "fin", "sector": "general_government", "summary_key": "loans", "summary_side": "sources"},
        "plain_english": "Government loan borrowing exists but is much smaller than bond financing in this dataset.",
        "jargon": "Recorded as general government net incurrence of loan liabilities.",
        "default_visible": False,
    },
    {
        "id": "financial_to_government_bonds",
        "source": "financial_institutions",
        "target": "government",
        "label": "Government bonds",
        "label_cn": "政府债券融资",
        "accounting_term": "Debt securities liabilities",
        "accounting_term_cn": "债券负债增加",
        "category": "securities",
        "metaphor_role": "debt_channel",
        "evidence_level": "direct_official_flow_simplified_holder",
        "extract": {"table": "fin", "sector": "general_government", "summary_key": "debt_securities", "summary_side": "sources"},
        "plain_english": "Government mainly borrows through bonds in this flow view.",
        "jargon": "Recorded as general government net incurrence of debt securities liabilities. Drawn from financial institutions for teaching clarity.",
        "default_visible": True,
    },
    {
        "id": "financial_to_firms_bonds",
        "source": "financial_institutions",
        "target": "firms",
        "label": "Corporate bonds",
        "label_cn": "企业债券融资",
        "accounting_term": "Debt securities liabilities",
        "accounting_term_cn": "债券负债增加",
        "category": "securities",
        "metaphor_role": "debt_channel",
        "evidence_level": "direct_official_flow_simplified_holder",
        "extract": {"table": "fin", "sector": "non_financial_corporations", "summary_key": "debt_securities", "summary_side": "sources"},
        "plain_english": "Firms also borrow through bonds, though this flow is much smaller than loans in 2023.",
        "jargon": "Recorded as nonfinancial corporations' net incurrence of debt securities liabilities.",
        "default_visible": False,
    },

    # Investment / capital formation
    {
        "id": "firms_to_production_investment",
        "source": "firms",
        "target": "production_engine",
        "label": "Business investment",
        "label_cn": "企业资本形成",
        "accounting_term": "Gross capital formation",
        "accounting_term_cn": "资本形成总额",
        "category": "investment",
        "metaphor_role": "future_oxygen_generation",
        "evidence_level": "direct_official_flow_simplified_process",
        "extract": {"table": "nf", "sector": "non_financial_enterprises", "side": "uses", "summary_key": "gross_capital_formation", "summary_side": "uses"},
        "plain_english": "Firms invest in capital formation. This can support future production, but it is not the same as immediate household consumption.",
        "jargon": "Recorded as nonfinancial enterprise gross capital formation.",
        "default_visible": True,
    },
    {
        "id": "government_to_production_public_investment",
        "source": "government",
        "target": "production_engine",
        "label": "Public investment",
        "label_cn": "公共资本形成",
        "accounting_term": "Gross capital formation",
        "accounting_term_cn": "资本形成总额",
        "category": "investment",
        "metaphor_role": "future_oxygen_generation",
        "evidence_level": "direct_official_flow_simplified_process",
        "extract": {"table": "nf", "sector": "genaral_governments", "side": "uses", "summary_key": "gross_capital_formation", "summary_side": "uses"},
        "plain_english": "Government investment can support future production and public infrastructure.",
        "jargon": "Recorded as general government gross capital formation.",
        "default_visible": True,
    },
    {
        "id": "households_to_production_capital_formation",
        "source": "households",
        "target": "production_engine",
        "label": "Household capital formation",
        "label_cn": "住户资本形成",
        "accounting_term": "Gross capital formation",
        "accounting_term_cn": "资本形成总额",
        "category": "investment",
        "metaphor_role": "housing_like_investment",
        "evidence_level": "direct_official_flow_simplified_process",
        "extract": {"table": "nf", "sector": "households", "side": "uses", "summary_key": "gross_capital_formation", "summary_side": "uses"},
        "plain_english": "Households also have capital formation, often visually useful as a housing-like investment channel.",
        "jargon": "Recorded as household gross capital formation.",
        "default_visible": False,
    },

    # Conceptual future loop
    {
        "id": "production_to_households_future_income",
        "source": "production_engine",
        "target": "households",
        "label": "Future income loop",
        "label_cn": "未来收入循环",
        "accounting_term": "Conceptual feedback",
        "accounting_term_cn": "概念性反馈",
        "category": "conceptual",
        "metaphor_role": "future_oxygen_generation",
        "evidence_level": "conceptual_only",
        "extract": None,
        "value": None,
        "display_value": 1.0,
        "plain_english": "Investment may support future production and income, but this table does not prove the quality or timing of that return.",
        "jargon": "Conceptual feedback edge, not an official measured flow.",
        "caveat": "Render dashed and do not scale alongside official flows.",
        "default_visible": True,
    },
]

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def clean_cn_label(label: str) -> str:
    if not label:
        return ""
    s = label.strip().replace("　", " ").replace(" ", " ")
    s = re.sub(r"^[一二三四五六七八九十百]+、", "", s)
    s = re.sub(r"^[（(][一二三四五六七八九十]+[）)]", "", s)
    return s.strip()


def safe_div(num: Number, den: Number, default: Number = None) -> Number:
    if num is None or den is None:
        return default
    try:
        den_f = float(den)
        if den_f == 0 or math.isnan(den_f):
            return default
        return float(num) / den_f
    except Exception:
        return default


def round_num(x: Any, digits: int = 6) -> Any:
    if x is None:
        return None
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return round(x, digits)
    return x


def deep_round(obj: Any, digits: int = 6) -> Any:
    if isinstance(obj, dict):
        return {k: deep_round(v, digits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_round(v, digits) for v in obj]
    return round_num(obj, digits)


def load_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_sector(tree: Dict[str, Any], sector_id: str) -> Dict[str, Any]:
    for sec in tree["root"].get("children", []):
        if sec.get("sector_id") == sector_id:
            return sec
    raise KeyError(f"Sector not found: {sector_id}")


def get_side(sec: Dict[str, Any], side: str) -> Dict[str, Any]:
    for child in sec.get("children", []):
        if child.get("kind") == "side" and child.get("side") == side:
            return child
    raise KeyError(f"Side not found: {sec.get('sector_id')} / {side}")


def walk(node: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    yield node
    for child in node.get("children", []) or []:
        yield from walk(child)


def norm_value(x: Any) -> Number:
    if x is None or x == "":
        return None
    try:
        y = float(x)
    except Exception:
        return None
    if math.isnan(y):
        return None
    return y


def item_matches(item: Dict[str, Any], label_contains: str) -> bool:
    raw = item.get("label_cn", "") or ""
    clean = clean_cn_label(raw)
    return label_contains in raw or label_contains in clean


def find_item(sec: Dict[str, Any], side: str, label_contains: str) -> Optional[Dict[str, Any]]:
    side_node = get_side(sec, side)
    # Prefer top-level item, but fallback to any descendant.
    for item in side_node.get("children", []):
        if item_matches(item, label_contains):
            return item
    for item in walk(side_node):
        if item is not side_node and item_matches(item, label_contains):
            return item
    return None


def get_item_value(tree: Dict[str, Any], sector_id: str, side: str, label_contains: str) -> Number:
    sec = get_sector(tree, sector_id)
    item = find_item(sec, side, label_contains)
    return norm_value(item.get("value")) if item else None


def get_item_breakdown(tree: Dict[str, Any], sector_id: str, side: str, label_contains: str) -> List[Dict[str, Any]]:
    sec = get_sector(tree, sector_id)
    item = find_item(sec, side, label_contains)
    if not item:
        return []
    out = []
    for child in item.get("children", []) or []:
        v = norm_value(child.get("value"))
        if v is not None:
            out.append({
                "label": clean_cn_label(child.get("label_cn", "")),
                "label_cn": child.get("label_cn", ""),
                "value": v,
                "path_cn": child.get("path_cn", ""),
            })
    return out


def get_summary_value(tree: Dict[str, Any], sector_id: str, key: str, side: str) -> Number:
    sec = get_sector(tree, sector_id)
    return norm_value(sec.get("summary", {}).get(key, {}).get(side))


def source_ref_from_extract(tree_name: str, tree: Dict[str, Any], extract: Dict[str, Any]) -> Dict[str, Any]:
    sector_id = extract.get("sector")
    side = extract.get("side")
    ref: Dict[str, Any] = {"tree": tree_name, "sector_id": sector_id}
    if sector_id:
        try:
            sec = get_sector(tree, sector_id)
            ref.update({"sector_label_cn": sec.get("label_cn"), "sector_label_en": sec.get("label_en")})
        except KeyError:
            pass
    if side:
        ref["side"] = side
    if extract.get("summary_key"):
        ref["summary_key"] = extract.get("summary_key")
        ref["summary_side"] = extract.get("summary_side")
    if extract.get("item_label") and sector_id and side:
        try:
            sec = get_sector(tree, sector_id)
            item = find_item(sec, side, extract["item_label"])
            if item:
                ref.update({
                    "item_label_contains": extract["item_label"],
                    "item_label_cn": item.get("label_cn"),
                    "item_label_en": item.get("label_en"),
                    "path_cn": item.get("path_cn"),
                    "path_en": item.get("path_en"),
                    "row_index": item.get("row_index"),
                })
        except KeyError:
            pass
    if extract.get("transform"):
        ref["display_transform"] = extract["transform"]
    return ref


def extract_value(nf: Dict[str, Any], fin: Dict[str, Any], extract: Optional[Dict[str, Any]]) -> Tuple[Number, Number, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return raw value, display value, source refs, breakdown."""
    if not extract:
        return None, None, [], []
    tree_name = extract.get("table")
    tree = nf if tree_name == "nf" else fin
    value: Number
    if extract.get("summary_key"):
        value = get_summary_value(tree, extract["sector"], extract["summary_key"], extract["summary_side"])
    elif extract.get("item_label"):
        value = get_item_value(tree, extract["sector"], extract["side"], extract["item_label"])
    else:
        value = None
    display = value
    if value is not None and extract.get("transform") == "abs":
        display = abs(value)
    breakdown: List[Dict[str, Any]] = []
    if extract.get("include_children") and extract.get("item_label"):
        breakdown = get_item_breakdown(tree, extract["sector"], extract["side"], extract["item_label"])
    return value, display, [source_ref_from_extract(tree_name, tree, extract)], breakdown


def v_nf(nf: Dict[str, Any], sector: str, key: str, side: str) -> Number:
    return get_summary_value(nf, sector, key, side)


def v_fin(fin: Dict[str, Any], sector: str, key: str, side: str) -> Number:
    return get_summary_value(fin, sector, key, side)


def item_nf(nf: Dict[str, Any], sector: str, side: str, label: str) -> Number:
    return get_item_value(nf, sector, side, label)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def calculate_global_metrics(nf: Dict[str, Any], fin: Dict[str, Any]) -> Dict[str, Any]:
    domestic_value_added = v_nf(nf, "total_of_domestic_sectors", "value_added", "sources")
    domestic_disposable_income = v_nf(nf, "total_of_domestic_sectors", "disposable_income", "sources")
    domestic_final_consumption = item_nf(nf, "total_of_domestic_sectors", "uses", "实际最终消费")
    domestic_gross_saving = v_nf(nf, "total_of_domestic_sectors", "gross_saving", "sources")
    domestic_gross_capital_formation = v_nf(nf, "total_of_domestic_sectors", "gross_capital_formation", "uses")
    net_exports_raw = item_nf(nf, "rest_of_the_world", "sources", "净出口")
    total_labor_compensation_paid = item_nf(nf, "total_of_domestic_sectors", "uses", "劳动者报酬")
    total_labor_compensation_received = item_nf(nf, "total_of_domestic_sectors", "sources", "劳动者报酬")

    return deep_round({
        "domestic_value_added": domestic_value_added,
        "domestic_disposable_income": domestic_disposable_income,
        "domestic_final_consumption": domestic_final_consumption,
        "domestic_gross_saving": domestic_gross_saving,
        "domestic_gross_capital_formation": domestic_gross_capital_formation,
        "domestic_net_financial_investment_nonfinancial": v_nf(nf, "total_of_domestic_sectors", "net_financial_investment", "uses"),
        "domestic_net_financial_investment_financial": v_fin(fin, "all_domestic_sectors", "net_financial_investment", "uses"),
        "total_labor_compensation_paid": total_labor_compensation_paid,
        "total_labor_compensation_received": total_labor_compensation_received,
        "net_exports_raw": net_exports_raw,
        "net_exports_display_value": abs(net_exports_raw) if net_exports_raw is not None else None,
        "shares": {
            "labor_compensation_paid_to_value_added": safe_div(total_labor_compensation_paid, domestic_value_added),
            "labor_compensation_received_to_value_added": safe_div(total_labor_compensation_received, domestic_value_added),
            "domestic_consumption_to_value_added": safe_div(domestic_final_consumption, domestic_value_added),
            "domestic_saving_to_value_added": safe_div(domestic_gross_saving, domestic_value_added),
            "capital_formation_to_value_added": safe_div(domestic_gross_capital_formation, domestic_value_added),
            "net_exports_to_value_added_abs": safe_div(abs(net_exports_raw) if net_exports_raw is not None else None, domestic_value_added),
        },
    })


def calculate_node_metrics(nf: Dict[str, Any], fin: Dict[str, Any], global_metrics: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    dva = global_metrics["domestic_value_added"]

    households = {
        "value_added": v_nf(nf, "households", "value_added", "sources"),
        "compensation_paid": v_nf(nf, "households", "compensation_of_employees", "uses"),
        "compensation_received": v_nf(nf, "households", "compensation_of_employees", "sources"),
        "disposable_income": v_nf(nf, "households", "disposable_income", "sources"),
        "adjusted_disposable_income": item_nf(nf, "households", "sources", "调整后可支配总收入"),
        "actual_final_consumption": item_nf(nf, "households", "uses", "实际最终消费"),
        "gross_saving": v_nf(nf, "households", "gross_saving", "sources"),
        "gross_capital_formation": v_nf(nf, "households", "gross_capital_formation", "uses"),
        "net_financial_investment_nonfinancial": v_nf(nf, "households", "net_financial_investment", "uses"),
        "net_financial_investment_financial": v_fin(fin, "households", "net_financial_investment", "uses"),
        "property_income_received": item_nf(nf, "households", "sources", "财产收入"),
        "property_income_paid": item_nf(nf, "households", "uses", "财产收入"),
        "current_transfers_received": item_nf(nf, "households", "sources", "经常转移"),
        "current_transfers_paid": item_nf(nf, "households", "uses", "经常转移"),
        "financial_uses_total": v_fin(fin, "households", "financial_uses_total", "uses"),
        "financial_sources_total": v_fin(fin, "households", "financial_sources_total", "sources"),
        "currency": v_fin(fin, "households", "currency", "uses"),
        "deposits": v_fin(fin, "households", "deposits", "uses"),
        "time_deposits": get_item_value(fin, "households", "uses", "定期存款"),
        "demand_deposits": get_item_value(fin, "households", "uses", "活期存款"),
        "insurance_reserves": v_fin(fin, "households", "insurance_reserves", "uses"),
        "loan_liabilities": v_fin(fin, "households", "loans", "sources"),
    }
    households_ind = {
        "consumption_rate_adjusted_income": safe_div(households["actual_final_consumption"], households["adjusted_disposable_income"]),
        "consumption_rate_disposable_income": safe_div(households["actual_final_consumption"], households["disposable_income"]),
        "saving_rate_adjusted_income": safe_div(households["gross_saving"], households["adjusted_disposable_income"]),
        "saving_rate_disposable_income": safe_div(households["gross_saving"], households["disposable_income"]),
        "deposit_share_of_financial_assets": safe_div(households["deposits"], households["financial_uses_total"]),
        "time_deposit_share_of_deposits": safe_div(households["time_deposits"], households["deposits"]),
        "insurance_share_of_financial_assets": safe_div(households["insurance_reserves"], households["financial_uses_total"]),
        "loan_liability_to_financial_asset_acquisition": safe_div(households["loan_liabilities"], households["financial_uses_total"]),
        "net_lender_pressure": safe_div(households["net_financial_investment_financial"], households["adjusted_disposable_income"]),
    }

    firms = {
        "value_added": v_nf(nf, "non_financial_enterprises", "value_added", "sources"),
        "compensation_paid": v_nf(nf, "non_financial_enterprises", "compensation_of_employees", "uses"),
        "production_taxes_paid": item_nf(nf, "non_financial_enterprises", "uses", "生产税净额"),
        "property_income_paid": item_nf(nf, "non_financial_enterprises", "uses", "财产收入"),
        "property_income_received": item_nf(nf, "non_financial_enterprises", "sources", "财产收入"),
        "current_transfers_paid": item_nf(nf, "non_financial_enterprises", "uses", "经常转移"),
        "current_transfers_received": item_nf(nf, "non_financial_enterprises", "sources", "经常转移"),
        "disposable_income": v_nf(nf, "non_financial_enterprises", "disposable_income", "sources"),
        "gross_saving": v_nf(nf, "non_financial_enterprises", "gross_saving", "sources"),
        "gross_capital_formation": v_nf(nf, "non_financial_enterprises", "gross_capital_formation", "uses"),
        "net_financial_investment_nonfinancial": v_nf(nf, "non_financial_enterprises", "net_financial_investment", "uses"),
        "net_financial_investment_financial": v_fin(fin, "non_financial_corporations", "net_financial_investment", "uses"),
        "financial_uses_total": v_fin(fin, "non_financial_corporations", "financial_uses_total", "uses"),
        "financial_sources_total": v_fin(fin, "non_financial_corporations", "financial_sources_total", "sources"),
        "deposits": v_fin(fin, "non_financial_corporations", "deposits", "uses"),
        "loan_liabilities": v_fin(fin, "non_financial_corporations", "loans", "sources"),
        "debt_security_liabilities": v_fin(fin, "non_financial_corporations", "debt_securities", "sources"),
    }
    firms_ind = {
        "wage_payout_rate_value_added": safe_div(firms["compensation_paid"], firms["value_added"]),
        "investment_to_value_added": safe_div(firms["gross_capital_formation"], firms["value_added"]),
        "investment_to_gross_saving": safe_div(firms["gross_capital_formation"], firms["gross_saving"]),
        "borrowing_gap_to_capital_formation": safe_div(abs(firms["net_financial_investment_nonfinancial"] or 0), firms["gross_capital_formation"]),
        "loan_share_of_financial_sources": safe_div(firms["loan_liabilities"], firms["financial_sources_total"]),
    }

    government = {
        "value_added": v_nf(nf, "genaral_governments", "value_added", "sources"),
        "compensation_paid": v_nf(nf, "genaral_governments", "compensation_of_employees", "uses"),
        "production_taxes_received": item_nf(nf, "genaral_governments", "sources", "生产税净额"),
        "current_transfers_received": item_nf(nf, "genaral_governments", "sources", "经常转移"),
        "current_transfers_paid": item_nf(nf, "genaral_governments", "uses", "经常转移"),
        "social_transfers_in_kind_paid": item_nf(nf, "genaral_governments", "uses", "实物社会转移"),
        "disposable_income": v_nf(nf, "genaral_governments", "disposable_income", "sources"),
        "adjusted_disposable_income": item_nf(nf, "genaral_governments", "sources", "调整后可支配总收入"),
        "actual_final_consumption": item_nf(nf, "genaral_governments", "uses", "实际最终消费"),
        "gross_saving": v_nf(nf, "genaral_governments", "gross_saving", "sources"),
        "gross_capital_formation": v_nf(nf, "genaral_governments", "gross_capital_formation", "uses"),
        "net_financial_investment_nonfinancial": v_nf(nf, "genaral_governments", "net_financial_investment", "uses"),
        "net_financial_investment_financial": v_fin(fin, "general_government", "net_financial_investment", "uses"),
        "financial_uses_total": v_fin(fin, "general_government", "financial_uses_total", "uses"),
        "financial_sources_total": v_fin(fin, "general_government", "financial_sources_total", "sources"),
        "deposits": v_fin(fin, "general_government", "deposits", "uses"),
        "loan_liabilities": v_fin(fin, "general_government", "loans", "sources"),
        "debt_security_liabilities": v_fin(fin, "general_government", "debt_securities", "sources"),
    }
    gov_spend_invest = (government["actual_final_consumption"] or 0) + (government["gross_capital_formation"] or 0)
    government_ind = {
        "saving_rate_disposable_income": safe_div(government["gross_saving"], government["disposable_income"]),
        "public_consumption_to_disposable_income": safe_div(government["actual_final_consumption"], government["disposable_income"]),
        "public_investment_to_disposable_income": safe_div(government["gross_capital_formation"], government["disposable_income"]),
        "borrowing_gap_to_spending_and_investment": safe_div(abs(government["net_financial_investment_nonfinancial"] or 0), gov_spend_invest),
        "bond_share_of_financial_sources": safe_div(government["debt_security_liabilities"], government["financial_sources_total"]),
    }

    finance = {
        "value_added": v_nf(nf, "financial_institutions", "value_added", "sources"),
        "compensation_paid": v_nf(nf, "financial_institutions", "compensation_of_employees", "uses"),
        "gross_saving": v_nf(nf, "financial_institutions", "gross_saving", "sources"),
        "gross_capital_formation": v_nf(nf, "financial_institutions", "gross_capital_formation", "uses"),
        "net_financial_investment_nonfinancial": v_nf(nf, "financial_institutions", "net_financial_investment", "uses"),
        "net_financial_investment_financial": v_fin(fin, "financial_institutions", "net_financial_investment", "uses"),
        "financial_uses_total": v_fin(fin, "financial_institutions", "financial_uses_total", "uses"),
        "financial_sources_total": v_fin(fin, "financial_institutions", "financial_sources_total", "sources"),
        "deposit_assets": v_fin(fin, "financial_institutions", "deposits", "uses"),
        "deposit_liabilities": v_fin(fin, "financial_institutions", "deposits", "sources"),
        "loan_assets": v_fin(fin, "financial_institutions", "loans", "uses"),
        "loan_liabilities": v_fin(fin, "financial_institutions", "loans", "sources"),
        "debt_security_assets": v_fin(fin, "financial_institutions", "debt_securities", "uses"),
        "debt_security_liabilities": v_fin(fin, "financial_institutions", "debt_securities", "sources"),
        "insurance_reserve_liabilities": v_fin(fin, "financial_institutions", "insurance_reserves", "sources"),
    }
    finance_ind = {
        "loan_assets_to_deposit_liabilities": safe_div(finance["loan_assets"], finance["deposit_liabilities"]),
        "security_assets_to_deposit_liabilities": safe_div(finance["debt_security_assets"], finance["deposit_liabilities"]),
        "financial_asset_expansion_to_value_added": safe_div(finance["financial_uses_total"], finance["value_added"]),
        "net_financial_investment_to_financial_uses": safe_div(finance["net_financial_investment_financial"], finance["financial_uses_total"]),
    }

    row = {
        "net_exports_raw": item_nf(nf, "rest_of_the_world", "sources", "净出口"),
        "compensation_paid_to_domestic": item_nf(nf, "rest_of_the_world", "uses", "劳动者报酬"),
        "compensation_received_from_domestic": item_nf(nf, "rest_of_the_world", "sources", "劳动者报酬"),
        "property_income_paid_to_domestic": item_nf(nf, "rest_of_the_world", "uses", "财产收入"),
        "property_income_received_from_domestic": item_nf(nf, "rest_of_the_world", "sources", "财产收入"),
        "current_transfers_paid_to_domestic": item_nf(nf, "rest_of_the_world", "uses", "经常转移"),
        "current_transfers_received_from_domestic": item_nf(nf, "rest_of_the_world", "sources", "经常转移"),
        "gross_saving": v_nf(nf, "rest_of_the_world", "gross_saving", "sources"),
        "net_financial_investment_nonfinancial": v_nf(nf, "rest_of_the_world", "net_financial_investment", "uses"),
        "net_financial_investment_financial": v_fin(fin, "the_rest_of_the_world", "net_financial_investment", "uses"),
    }
    row["net_exports_display_value"] = abs(row["net_exports_raw"]) if row["net_exports_raw"] is not None else None
    row_ind = {
        "net_exports_to_domestic_value_added_abs": safe_div(row["net_exports_display_value"], dva),
        "external_property_income_balance": (row["property_income_received_from_domestic"] or 0) - (row["property_income_paid_to_domestic"] or 0),
        "external_property_income_balance_to_value_added": safe_div(abs(((row["property_income_received_from_domestic"] or 0) - (row["property_income_paid_to_domestic"] or 0))), dva),
    }

    production = {
        "domestic_value_added": global_metrics["domestic_value_added"],
        "gross_capital_formation": global_metrics["domestic_gross_capital_formation"],
        "domestic_final_consumption": global_metrics["domestic_final_consumption"],
    }
    production_ind = {
        "investment_intensity": safe_div(production["gross_capital_formation"], production["domestic_value_added"]),
        "consumption_intensity": safe_div(production["domestic_final_consumption"], production["domestic_value_added"]),
    }

    node_metrics = {
        "households": {"metrics": households, "indicators": households_ind, "health": {
            "oxygen_delivery_score": households_ind["consumption_rate_adjusted_income"],
            "clotting_score": households_ind["time_deposit_share_of_deposits"],
            "deposit_concentration_score": households_ind["deposit_share_of_financial_assets"],
            "swelling_score": households_ind["net_lender_pressure"],
            "borrowing_pressure_score": households_ind["loan_liability_to_financial_asset_acquisition"],
            "red_blood_cell_state": ["oxygen_delivery", "clotting", "net_lender"],
            "plain_english": "Households consume a large amount, but also save heavily. New household financial assets are concentrated in deposits, especially time deposits.",
        }},
        "firms": {"metrics": firms, "indicators": firms_ind, "health": {
            "wage_delivery_score": firms_ind["wage_payout_rate_value_added"],
            "investment_intensity": firms_ind["investment_to_value_added"],
            "borrowing_pressure_score": firms_ind["borrowing_gap_to_capital_formation"],
            "loan_dependency_score": firms_ind["loan_share_of_financial_sources"],
            "red_blood_cell_state": ["income_creation", "investment_loop", "debt_dependency"],
            "plain_english": "Firms generate most value added and pay much labor income, but investment exceeds their own saving, so they rely heavily on borrowing.",
        }},
        "government": {"metrics": government, "indicators": government_ind, "health": {
            "saving_score": government_ind["saving_rate_disposable_income"],
            "borrowing_pressure_score": government_ind["borrowing_gap_to_spending_and_investment"],
            "bond_dependency_score": government_ind["bond_share_of_financial_sources"],
            "red_blood_cell_state": ["redistribution_valve", "debt_financed_spending"],
            "plain_english": "In this flow view, government is not a hoarding node: it has negative saving and net borrowing, financed mainly through bonds.",
        }},
        "financial_institutions": {"metrics": finance, "indicators": finance_ind, "health": {
            "recirculation_score": finance_ind["loan_assets_to_deposit_liabilities"],
            "securities_loop_score": finance_ind["security_assets_to_deposit_liabilities"],
            "financial_scale_score": finance_ind["financial_asset_expansion_to_value_added"],
            "red_blood_cell_state": ["recirculation_pump", "possible_empty_spinning"],
            "plain_english": "The financial system transforms deposits and other liabilities into loans and securities. This is where saved money may re-enter production or loop through finance/debt.",
        }},
        "rest_of_world": {"metrics": row, "indicators": row_ind, "health": {
            "external_oxygen_score": row_ind["net_exports_to_domestic_value_added_abs"],
            "cross_border_income_pressure": row_ind["external_property_income_balance_to_value_added"],
            "red_blood_cell_state": ["external_oxygen"],
            "plain_english": "Rest of World represents external demand and cross-border income. Net exports are drawn as money/demand flowing from foreign buyers into domestic producers.",
        }},
        "production_engine": {"metrics": production, "indicators": production_ind, "health": {
            "investment_intensity": production_ind["investment_intensity"],
            "oxygen_delivery_score": production_ind["consumption_intensity"],
            "red_blood_cell_state": ["future_oxygen_generation"],
            "plain_english": "Production is not a wallet. It is the engine turning labor, capital, and demand into income.",
        }},
    }
    return deep_round(node_metrics)


def primary_denominators(calculated_nodes: Dict[str, Dict[str, Any]]) -> Dict[str, Number]:
    def m(node_id: str, key: str) -> Number:
        return calculated_nodes.get(node_id, {}).get("metrics", {}).get(key)
    return {
        "households": m("households", "adjusted_disposable_income") or m("households", "disposable_income"),
        "firms": m("firms", "value_added"),
        "government": m("government", "disposable_income"),
        "financial_institutions": m("financial_institutions", "financial_uses_total"),
        "rest_of_world": m("rest_of_world", "net_exports_display_value"),
        "production_engine": m("production_engine", "domestic_value_added"),
    }


def calculate_edges(nf: Dict[str, Any], fin: Dict[str, Any], global_metrics: Dict[str, Any], calculated_nodes: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    denominators = primary_denominators(calculated_nodes)
    edges: Dict[str, Dict[str, Any]] = {}
    category_totals: Dict[str, float] = defaultdict(float)
    all_measured_total = 0.0

    for spec in EDGE_SPECS:
        spec = copy.deepcopy(spec)
        value = spec.get("value")
        display_value = spec.get("display_value", value)
        refs: List[Dict[str, Any]] = []
        breakdown: List[Dict[str, Any]] = []
        if spec.get("extract") is not None:
            value, display_value, refs, breakdown = extract_value(nf, fin, spec.get("extract"))
        if display_value is not None and spec["category"] != "conceptual":
            category_totals[spec["category"]] += abs(float(display_value))
            all_measured_total += abs(float(display_value))
        edges[spec["id"]] = {
            "id": spec["id"],
            "source": spec["source"],
            "target": spec["target"],
            "label": spec["label"],
            "label_cn": spec.get("label_cn"),
            "accounting_term": spec.get("accounting_term"),
            "accounting_term_cn": spec.get("accounting_term_cn"),
            "category": spec["category"],
            "flow_nature": spec.get("flow_nature", spec["category"]),
            "evidence_level": spec["evidence_level"],
            "value": value,
            "display_value": display_value,
            "unit": "亿元" if value is not None else None,
            "metaphor": {
                "role": spec.get("metaphor_role"),
                "particle_style": metaphor_to_particle_style(spec.get("metaphor_role")),
                "diagnostic_weight": 1.0 if spec["category"] != "conceptual" else 0.0,
            },
            "source_refs": refs,
            "breakdown": breakdown,
            "explain": {
                "plain_english": spec.get("plain_english"),
                "jargon": spec.get("jargon"),
                "caveat": spec.get("caveat"),
            },
            "visual_hints": {
                "default_visible": bool(spec.get("default_visible", True)),
                "show_particles": spec["category"] != "conceptual",
                "stroke_style": "dashed" if spec["category"] == "conceptual" else "solid",
                "width_metric": "display_value",
                "particle_rate_metric": "display_value",
            },
        }

    # Add percentages after category totals are known.
    for edge in edges.values():
        val = edge.get("display_value")
        if val is None or edge["category"] == "conceptual":
            edge["percentages"] = {
                "of_domestic_value_added": None,
                "of_source_node_primary_metric": None,
                "of_target_node_primary_metric": None,
                "of_category_total": None,
                "of_all_measured_edges": None,
            }
            continue
        abs_val = abs(float(val))
        edge["percentages"] = {
            "of_domestic_value_added": safe_div(abs_val, global_metrics.get("domestic_value_added")),
            "of_source_node_primary_metric": safe_div(abs_val, denominators.get(edge["source"])),
            "of_target_node_primary_metric": safe_div(abs_val, denominators.get(edge["target"])),
            "of_category_total": safe_div(abs_val, category_totals.get(edge["category"])),
            "of_all_measured_edges": safe_div(abs_val, all_measured_total),
        }

    return deep_round(edges)


def metaphor_to_particle_style(role: Optional[str]) -> str:
    if role in {"oxygen_delivery", "public_oxygen_delivery", "external_oxygen"}:
        return "healthy"
    if role in {"clotting", "slow_saving_pool", "storage_pool"}:
        return "slow"
    if role in {"credit_recirculation", "recirculation_pump"}:
        return "pumped"
    if role in {"debt_channel", "debt_dependency"}:
        return "warning"
    if role in {"future_oxygen_generation", "housing_like_investment"}:
        return "future"
    if role and role.startswith("redistribution"):
        return "valve"
    if role == "public_service_delivery":
        return "service"
    return "neutral"


def calculate_diagnostics(global_metrics: Dict[str, Any], nodes: Dict[str, Any], edges: Dict[str, Any]) -> Dict[str, Any]:
    h = nodes["households"]["indicators"]
    f = nodes["firms"]["indicators"]
    g = nodes["government"]["indicators"]
    fin = nodes["financial_institutions"]["indicators"]
    row = nodes["rest_of_world"]["indicators"]

    def edge_ids_by_role(role: str) -> List[str]:
        return [eid for eid, e in edges.items() if e.get("metaphor", {}).get("role") == role]

    return deep_round({
        "red_blood_cell": {
            "oxygen_delivery": {
                "definition": "Money reaches final demand and supports producer revenue.",
                "main_edges": ["households_to_firms_consumption", "government_to_firms_public_consumption", "rest_world_to_firms_net_exports"],
                "score": (global_metrics["shares"].get("domestic_consumption_to_value_added") or 0) + (global_metrics["shares"].get("net_exports_to_value_added_abs") or 0),
                "components": {
                    "domestic_final_consumption_to_value_added": global_metrics["shares"].get("domestic_consumption_to_value_added"),
                    "net_exports_to_value_added_abs": global_metrics["shares"].get("net_exports_to_value_added_abs"),
                    "household_consumption_rate_adjusted_income": h.get("consumption_rate_adjusted_income"),
                },
            },
            "clotting": {
                "definition": "Money pools as deposits or low-velocity financial storage.",
                "main_edges": ["households_to_financial_deposits", "households_to_financial_insurance"],
                "score": h.get("time_deposit_share_of_deposits"),
                "components": {
                    "household_deposit_share_of_financial_assets": h.get("deposit_share_of_financial_assets"),
                    "household_time_deposit_share": h.get("time_deposit_share_of_deposits"),
                    "household_saving_rate_adjusted_income": h.get("saving_rate_adjusted_income"),
                },
            },
            "recirculation": {
                "definition": "The financial system turns deposits and liabilities into credit and securities.",
                "main_edges": ["financial_to_firms_loans", "financial_to_households_loans", "financial_to_government_bonds"],
                "score": fin.get("loan_assets_to_deposit_liabilities"),
                "components": {
                    "financial_loans_to_deposit_liabilities": fin.get("loan_assets_to_deposit_liabilities"),
                    "financial_security_assets_to_deposit_liabilities": fin.get("security_assets_to_deposit_liabilities"),
                    "financial_asset_expansion_to_value_added": fin.get("financial_asset_expansion_to_value_added"),
                },
            },
            "empty_spinning": {
                "definition": "Funds circulate through investment/credit loops without necessarily becoming household consumption quickly.",
                "main_edges": ["financial_to_firms_loans", "financial_to_government_bonds", "firms_to_production_investment", "government_to_production_public_investment"],
                "score": max(x for x in [f.get("borrowing_gap_to_capital_formation"), g.get("borrowing_gap_to_spending_and_investment")] if x is not None),
                "components": {
                    "firm_borrowing_gap_to_capital_formation": f.get("borrowing_gap_to_capital_formation"),
                    "government_borrowing_gap_to_spending_and_investment": g.get("borrowing_gap_to_spending_and_investment"),
                    "firm_investment_to_gross_saving": f.get("investment_to_gross_saving"),
                },
                "caveat": "This is an interpretive diagnostic, not an official statistical category.",
            },
            "external_oxygen": {
                "definition": "External demand enters the domestic circulation through the Rest of World node.",
                "main_edges": ["rest_world_to_firms_net_exports"],
                "score": row.get("net_exports_to_domestic_value_added_abs"),
                "components": {
                    "net_exports_to_domestic_value_added_abs": row.get("net_exports_to_domestic_value_added_abs"),
                },
                "caveat": "Uses net exports, not gross exports; not a complete export-reliance indicator.",
            },
            "debt_absorption": {
                "definition": "Future income is absorbed by repayment or debt service.",
                "main_edges": [],
                "score": None,
                "caveat": "Debt service is not cleanly measured as a direct edge in the current flow tree files. Use as annotation only.",
            },
        }
    })


def merge_graph(manual: Dict[str, Any], calculated_nodes: Dict[str, Any], calculated_edges: Dict[str, Any]) -> Dict[str, Any]:
    nodes = []
    for node in manual["nodes"]:
        nid = node["id"]
        merged = copy.deepcopy(node)
        merged.update(calculated_nodes.get(nid, {}))
        nodes.append(merged)

    # Preserve manual EDGE_SPECS order.
    edges = [calculated_edges[e["id"]] for e in EDGE_SPECS if e["id"] in calculated_edges]
    return {"nodes": nodes, "edges": edges}


def validate_output(manual: Dict[str, Any], graph: Dict[str, Any], calculated_edges: Dict[str, Any]) -> Dict[str, Any]:
    node_ids = {n["id"] for n in graph["nodes"]}
    edge_ids = {e["id"] for e in graph["edges"]}
    missing_endpoints = []
    missing_values = []
    conceptual_not_marked = []
    negative_measured = []
    for edge in graph["edges"]:
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            missing_endpoints.append(edge["id"])
        if edge["category"] != "conceptual" and edge.get("display_value") is None:
            missing_values.append(edge["id"])
        if edge["category"] == "conceptual" and edge.get("evidence_level") != "conceptual_only":
            conceptual_not_marked.append(edge["id"])
        if edge["category"] != "conceptual" and edge.get("display_value") is not None and edge.get("display_value") < 0:
            negative_measured.append(edge["id"])
    return {
        "source_tree_validation_note": "Run validate_fof_trees.py separately; expected current result is hard failures = 0, with bridge discrepancies as warnings.",
        "all_sources_and_targets_exist": not missing_endpoints,
        "all_measured_edges_have_display_values": not missing_values,
        "conceptual_edges_marked": not conceptual_not_marked,
        "negative_display_values_handled": not negative_measured,
        "missing_endpoints": missing_endpoints,
        "missing_values": missing_values,
        "conceptual_not_marked": conceptual_not_marked,
        "negative_measured_display_values": negative_measured,
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "default_visible_edge_count": sum(1 for e in graph["edges"] if e.get("visual_hints", {}).get("default_visible")),
    }


def build_output(nf_path: str | Path, fin_path: str | Path) -> Dict[str, Any]:
    nf = load_json(nf_path)
    fin = load_json(fin_path)

    global_metrics = calculate_global_metrics(nf, fin)
    calculated_nodes = calculate_node_metrics(nf, fin, global_metrics)
    calculated_edges = calculate_edges(nf, fin, global_metrics, calculated_nodes)
    diagnostics = calculate_diagnostics(global_metrics, calculated_nodes, calculated_edges)
    graph = merge_graph(MANUAL_SPEC, calculated_nodes, calculated_edges)
    validation = validate_output(MANUAL_SPEC, graph, calculated_edges)

    output = {
        "metadata": {
            **MANUAL_SPEC["metadata"],
            "source_files": {
                "nonfinancial_tree": str(nf_path),
                "financial_tree": str(fin_path),
            },
            "source_tables": [
                nf.get("metadata", {}).get("title_cn"),
                fin.get("metadata", {}).get("title_cn"),
            ],
            "data_mode": "annual_flow_2023",
            "units": {
                "base_unit": "亿元",
                "display_options": [
                    {"unit": "亿元", "factor": 1},
                    {"unit": "万亿元", "factor": 0.0001},
                ],
            },
        },
        "manual": {
            "description": "Editable/story layer. Tweak labels, copy, layout, scenes, and visibility here or in the script.",
            "nodes": MANUAL_SPEC["nodes"],
            "edge_specs": [{k: v for k, v in spec.items() if k != "extract"} for spec in EDGE_SPECS],
            "edge_categories": MANUAL_SPEC["edge_categories"],
            "glossary": MANUAL_SPEC["glossary"],
            "scenes": MANUAL_SPEC["scenes"],
        },
        "calculated": {
            "description": "Automatically calculated from the sector-tree JSON files. Do not hand-edit unless you know you are overriding source data.",
            "global_metrics": global_metrics,
            "nodes": calculated_nodes,
            "edges": calculated_edges,
            "diagnostics": diagnostics,
        },
        "graph": {
            "description": "Merged D3-ready graph. D3 can read this directly.",
            **graph,
        },
        "scenes": MANUAL_SPEC["scenes"],
        "glossary": MANUAL_SPEC["glossary"],
        "validation": validation,
        "evidence_levels": {
            "direct_official_flow": "Directly read from one official table item.",
            "direct_official_flow_grouped": "Directly read from an official parent item; child breakdown included when available.",
            "direct_official_flow_simplified_counterparty": "Official value, but displayed as actor-to-actor edge for teaching clarity.",
            "direct_official_flow_simplified_lender": "Official borrower-side liability flow; lender is simplified as financial institutions.",
            "direct_official_flow_simplified_holder": "Official liability/security flow; holder is simplified as financial institutions.",
            "direct_official_flow_simplified_process": "Official flow displayed as actor-to-process edge for teaching clarity.",
            "direct_official_flow_sign_normalized": "Official flow whose sign/direction is normalized for money-flow visualization.",
            "direct_official_flow_non_cash_service": "Official flow that may represent services in kind rather than ordinary cash payments.",
            "conceptual_only": "Used for explanation; not a measured official flow.",
        },
    }
    return deep_round(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble actor-centered macro-circulation graph JSON from FOF sector trees.")
    parser.add_argument("nonfinancial_tree_json", help="Path to fof_nonfinancial_sector_tree_2023.json")
    parser.add_argument("financial_tree_json", help="Path to fof_financial_sector_tree_2023.json")
    parser.add_argument("-o", "--output", default="macro_circulation_graph_2023.json", help="Output JSON path")
    parser.add_argument("--compact", action="store_true", help="Write compact JSON instead of indented JSON")
    args = parser.parse_args()

    output = build_output(args.nonfinancial_tree_json, args.financial_tree_json)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=None if args.compact else 2)

    v = output["validation"]
    print(f"Wrote {args.output}")
    print(f"Nodes: {v['node_count']} | Edges: {v['edge_count']} | Default-visible edges: {v['default_visible_edge_count']}")
    print(f"Validation: endpoints={v['all_sources_and_targets_exist']} measured_values={v['all_measured_edges_have_display_values']} conceptual_marked={v['conceptual_edges_marked']} negative_handled={v['negative_display_values_handled']}")
    if not (v["all_sources_and_targets_exist"] and v["all_measured_edges_have_display_values"] and v["conceptual_edges_marked"] and v["negative_display_values_handled"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
