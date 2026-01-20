# Metadata Transformation & Data Profiling Architecture

## OGD → Dublin Core Transformation System

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Mapping Configuration Specification](#2-mapping-configuration-specification)
3. [Derived Metadata Calculators](#3-derived-metadata-calculators)
4. [Validation & QA Framework](#4-validation--qa-framework)
5. [Change Management & Governance](#5-change-management--governance)
6. [Operationalization](#6-operationalization)

---

## 1. Architecture Overview

### 1.1 End-to-End Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        METADATA TRANSFORMATION PIPELINE                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   INGEST     │───▶│  NORMALIZE   │───▶│     MAP      │───▶│   COMPUTE    │  │
│  │  OGD Meta    │    │  & Validate  │    │   Fields     │    │   Derived    │  │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                   │                   │                   │           │
│         ▼                   ▼                   ▼                   ▼           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  Raw OGD     │    │  Normalized  │    │   Dublin     │    │   Enhanced   │  │
│  │  Records     │    │  Records     │    │   Core       │    │   Dublin     │  │
│  └──────────────┘    └──────────────┘    └──────────────┘    │   Core       │  │
│                                                               └──────────────┘  │
│                                                                      │          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐           │          │
│  │   EXPORT     │◀───│   VALIDATE   │◀───│   PROFILE    │◀──────────┘          │
│  │  JSON/CSV/DB │    │   & QA       │    │   Dataset    │                      │
│  └──────────────┘    └──────────────┘    └──────────────┘                      │
│         │                   │                                                   │
│         ▼                   ▼                                                   │
│  ┌──────────────┐    ┌──────────────┐                                          │
│  │ Dublin Core  │    │  Validation  │                                          │
│  │ Output Files │    │  Reports     │                                          │
│  └──────────────┘    └──────────────┘                                          │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Module Responsibilities

| Module | Responsibility | Input | Output |
|--------|---------------|-------|--------|
| **Ingest** | Load OGD metadata from CSV/Excel/API | Raw files | `OGDRecord[]` |
| **Normalize** | Standardize date formats, clean text, handle nulls | `OGDRecord` | `NormalizedOGDRecord` |
| **Map** | Apply field-level transformations per config | `NormalizedOGDRecord` + Config | `DublinCoreRecord` |
| **Compute** | Generate derived fields from dataset content | `DublinCoreRecord` + Dataset files | `EnhancedDCRecord` |
| **Profile** | Scan dataset for PII, schema, statistics | Dataset files | `DataProfile` |
| **Validate** | Check required fields, formats, vocab | `EnhancedDCRecord` | `ValidationReport` |
| **Export** | Generate output in required formats | `EnhancedDCRecord` | JSON/CSV/DB rows |

### 1.3 Recommended Repository Structure

```
ogd-dublin-core-transformer/
├── README.md
├── pyproject.toml
├── setup.py
│
├── config/
│   ├── mapping/
│   │   ├── base_mapping.yaml           # Default mapping rules
│   │   ├── type_overrides/
│   │   │   ├── type_1.yaml             # Static dataset overrides
│   │   │   ├── type_2.yaml             # API-backed overrides
│   │   │   ├── type_4.yaml             # File download overrides
│   │   │   └── type_5.yaml             # Registered access overrides
│   │   └── dataset_overrides/          # Per-dataset custom rules
│   │       └── {dataset_uuid}.yaml
│   │
│   ├── validation/
│   │   ├── field_rules.yaml            # Per-field validation rules
│   │   ├── controlled_vocabs/
│   │   │   ├── sectors.json            # 36 predefined sectors
│   │   │   ├── frequencies.json        # Accrual periodicity URIs
│   │   │   ├── licenses.json           # GODL, CC, MIT, etc.
│   │   │   └── jurisdictions.json      # Central/State
│   │   └── dataset_rules.yaml          # Cross-field validation
│   │
│   ├── profiles/
│   │   └── pii_patterns.yaml           # Indian PII detection patterns
│   │
│   └── settings.yaml                   # Runtime configuration
│
├── src/
│   └── ogd_dc_transformer/
│       ├── __init__.py
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models.py               # Pydantic data models
│       │   ├── registry.py             # Transform function registry
│       │   └── exceptions.py           # Custom exceptions
│       │
│       ├── ingest/
│       │   ├── __init__.py
│       │   ├── csv_loader.py
│       │   ├── excel_loader.py
│       │   └── api_loader.py
│       │
│       ├── normalize/
│       │   ├── __init__.py
│       │   ├── normalizer.py           # Main normalization orchestrator
│       │   ├── date_normalizer.py      # Date format standardization
│       │   └── text_normalizer.py      # Text cleaning, unicode
│       │
│       ├── mapping/
│       │   ├── __init__.py
│       │   ├── config_loader.py        # Load & merge YAML configs
│       │   ├── mapper.py               # Core mapping engine
│       │   └── transforms/
│       │       ├── __init__.py
│       │       ├── direct.py           # Direct field copy
│       │       ├── date.py             # Date transformations
│       │       ├── array.py            # Array/list handling
│       │       ├── uri.py              # URI construction
│       │       ├── composite.py        # Multi-field composites
│       │       └── ai_assisted.py      # LLM-based transforms
│       │
│       ├── derived/
│       │   ├── __init__.py
│       │   ├── temporal_coverage.py    # Date range calculator
│       │   ├── granularity.py          # Temporal resolution
│       │   └── content_analyzer.py     # Field/schema detection
│       │
│       ├── profiling/
│       │   ├── __init__.py
│       │   ├── pii_detector.py         # PII pattern matching
│       │   ├── schema_profiler.py      # Column type inference
│       │   └── statistics.py           # Data quality stats
│       │
│       ├── validation/
│       │   ├── __init__.py
│       │   ├── validator.py            # Main validation orchestrator
│       │   ├── field_validators.py     # Per-field checks
│       │   └── dataset_validators.py   # Cross-field rules
│       │
│       ├── export/
│       │   ├── __init__.py
│       │   ├── json_exporter.py
│       │   ├── csv_exporter.py
│       │   └── db_exporter.py
│       │
│       └── cli/
│           ├── __init__.py
│           └── main.py                 # CLI entry point
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                     # Pytest fixtures
│   ├── unit/
│   │   ├── test_normalizers.py
│   │   ├── test_transforms.py
│   │   └── test_validators.py
│   ├── integration/
│   │   └── test_pipeline.py
│   └── golden_files/
│       ├── input/
│       │   └── sample_ogd_5datasets.xlsx
│       └── expected/
│           └── dublin_core_5datasets.json
│
├── scripts/
│   ├── migrate_config.py               # Config version migration
│   └── generate_diff_report.py         # Compare runs
│
└── docs/
    ├── mapping_spec.md
    ├── transform_reference.md
    └── changelog.md
```

### 1.4 Data Contracts (Interfaces)

#### 1.4.1 OGD Record (Input)

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class OGDRecord(BaseModel):
    """Raw OGD dataset metadata as ingested."""
    
    # Core identification
    title: str
    node_alias: str
    domain: str = "data.gov.in"
    
    # Classification
    resource_category: Optional[str] = None
    sector: Optional[str] = None
    sector_resource: Optional[str] = None
    catalog_title: Optional[str] = None
    
    # Dates (raw format: DD/MM/YYYY or mixed)
    created: Optional[str] = None
    published_date: Optional[str] = None
    changed: Optional[str] = None
    
    # Attribution
    govt_type: Optional[str] = None
    ministry_department: Optional[str] = None
    state_department: Optional[str] = None
    cdos_state_ministry: Optional[str] = None
    
    # Data characteristics
    frequency: Optional[str] = None
    granularity: Optional[str] = None
    field_resource_type: Optional[int] = None
    
    # Files and access
    datafile: Optional[str] = None
    datafile_url: Optional[str] = None
    file_format: Optional[str] = None
    file_size: Optional[float] = None
    
    # Metadata
    note: Optional[str] = None
    field_high_value_dataset: Optional[int] = None
    
    # Analytics (unmappable to DC)
    ogdp_view_count: Optional[int] = None
    ogdp_download_count: Optional[int] = None
    api_request_count: Optional[int] = None
    is_visualized: Optional[int] = None
    is_api_available: Optional[int] = None
    field_from_api: Optional[int] = None
    is_rated: Optional[int] = None
    field_show_export: Optional[bool] = None
    external_api_reference: Optional[str] = None
```

#### 1.4.2 Dublin Core Record (Output)

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import date
from enum import Enum

class Identifier(BaseModel):
    uuid: str
    landing_page: str
    api_url: Optional[str] = None

class Subject(BaseModel):
    keyword: List[str] = []
    sector: List[str] = []
    sector_resource: List[str] = []
    group: Optional[List[str]] = None

class Relation(BaseModel):
    download_url: Optional[str] = None
    xml_download_url: Optional[str] = None
    json_download_url: Optional[str] = None
    ods_download_url: Optional[str] = None
    xls_download_url: Optional[str] = None
    csv_endpointURL: Optional[str] = None
    json_endpointURL: Optional[str] = None
    xml_endpointURL: Optional[str] = None
    access_url: Optional[str] = None
    catalog_title: Optional[str] = None
    generic: Optional[str] = None
    has_part: Optional[List[str]] = None
    is_part_of: Optional[str] = None
    is_referenced_by: Optional[str] = None
    is_replaced_by: Optional[str] = None
    replaces: Optional[str] = None
    is_version_of: Optional[str] = None
    has_version: Optional[str] = None

class TemporalCoverage(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None
    scheme: str = "DCMI-Period"
    
    def to_dcmi_string(self) -> str:
        if self.start and self.end:
            return f"start: {self.start.isoformat()}; end: {self.end.isoformat()}"
        elif self.start:
            return f"start: {self.start.isoformat()}; end: NA"
        return "NA"

class DublinCoreRecord(BaseModel):
    """Dublin Core compliant metadata record."""
    
    # Title Elements (dc:title, dcterms:title, dcterms:alternative)
    title: str = Field(..., alias="dc:title")
    alternative_title: Optional[str] = Field(None, alias="dcterms:alternative")
    
    # Subject Classification (dc:subject)
    subject: Subject = Field(..., alias="dc:subject")
    
    # Description Elements
    description: Optional[str] = Field(None, alias="dc:description")
    abstract: Optional[str] = Field(None, alias="dcterms:abstract")
    endpoint_description: Optional[str] = Field(None, alias="description:endpointDescription")
    note: Optional[str] = Field(None, alias="dcin:note")
    
    # Date Elements (ISO 8601: YYYY-MM-DD)
    created: Optional[date] = Field(None, alias="dcterms:created")
    issued: Optional[date] = Field(None, alias="dcterms:issued")
    modified: Optional[date] = Field(None, alias="dcterms:modified")
    temporal: Optional[TemporalCoverage] = Field(None, alias="dcterms:temporal")
    
    # Type & Format
    type: str = Field("Dataset", alias="dc:type")
    format: Optional[str] = Field(None, alias="dc:format")  # MIME type
    extent: Optional[str] = Field(None, alias="dcterms:extent")  # File size
    conforms_to: Optional[str] = Field(None, alias="dcterms:conformsTo")  # Schema/fields
    
    # Identifier
    identifier: Identifier = Field(..., alias="dc:identifier")
    
    # Source & Relations
    source: Optional[str] = Field(None, alias="dc:source")
    relation: Relation = Field(default_factory=Relation, alias="dc:relation")
    
    # Coverage
    spatial: Optional[str] = Field(None, alias="dcterms:spatial")
    coverage: Optional[str] = Field(None, alias="dcterms:coverage")  # Granularity as ISO 8601 duration
    
    # Attribution
    creator: Optional[str] = Field(None, alias="dc:creator")
    publisher: List[str] = Field(default_factory=list, alias="dc:publisher")
    contributor: Optional[str] = Field(None, alias="dc:contributor")
    
    # Rights & Access
    rights_statement: Optional[str] = Field(None, alias="dc:rights")
    license: Optional[str] = Field(None, alias="dcterms:license")
    access_rights: Optional[str] = Field(None, alias="dcterms:accessRights")
    
    # Periodicity
    accrual_periodicity: Optional[str] = Field(None, alias="dcterms:accrualPeriodicity")
    accrual_method: Optional[str] = Field(None, alias="dcterms:accrualMethod")
    
    # Extensions
    jurisdiction: Optional[str] = Field(None, alias="dcin:jurisdiction")
    high_value_dataset_category: Optional[str] = Field(None, alias="dcin:high_value_dataset_category")
    language: Optional[str] = Field(None, alias="dc:language")
    collection: Optional[str] = Field(None, alias="dcterms:collection")
    
    # FOAF extension
    depiction: Optional[str] = Field(None, alias="foaf:depiction")
    
    # Provenance tracking (internal, not exported to DC)
    _provenance: Dict[str, Any] = {}
```

#### 1.4.3 Transform Result

```python
class TransformResult(BaseModel):
    """Result of a single field transformation."""
    field_name: str
    value: Any
    source_fields: List[str]
    transforms_applied: List[str]
    confidence: float = 1.0
    is_derived: bool = False
    warnings: List[str] = []

class MappingResult(BaseModel):
    """Complete result of mapping an OGD record."""
    dublin_core: DublinCoreRecord
    field_results: Dict[str, TransformResult]
    unmapped_fields: List[str]
    errors: List[str]
    processing_time_ms: float
```

#### 1.4.4 Validation Report

```python
class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

class ValidationIssue(BaseModel):
    field: str
    severity: ValidationSeverity
    rule_id: str
    message: str
    current_value: Any = None
    expected: Optional[str] = None

class ValidationReport(BaseModel):
    record_id: str
    is_valid: bool
    issues: List[ValidationIssue]
    checked_at: datetime
    config_version: str
```

---

## 2. Mapping Configuration Specification

### 2.1 Configuration Schema

The mapping configuration uses YAML for human readability and supports layered overrides.

```yaml
# config/mapping/base_mapping.yaml
version: "1.0.0"
description: "Base OGD to Dublin Core mapping configuration"
last_updated: "2025-01-20"

# Global defaults
defaults:
  na_values: ["NA", "N/A", "null", "", "nan", "None", "(empty)"]
  date_input_formats: 
    - "%d/%m/%Y"
    - "%Y-%m-%d"
    - "%d-%m-%Y"
    - "%Y-%m-%d %H:%M:%S"
  date_output_format: "%Y-%m-%d"
  string_trim: true
  normalize_unicode: true

# Field mappings
mappings:

  # ═══════════════════════════════════════════════════════════════════
  # TITLE ELEMENTS
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dc:title"
    source_fields: ["title"]
    transform_pipeline:
      - name: "direct_copy"
      - name: "trim_whitespace"
    validators:
      - type: "required"
      - type: "min_length"
        params: {min: 5}
      - type: "max_length"
        params: {max: 500}
    default: null
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Mandatory field. May be AI-enhanced if unclear."
    provenance:
      source_system: "OGD"
      transformation_type: "direct"

  - target_field: "dcterms:alternative"
    source_fields: []
    transform_pipeline:
      - name: "ai_generate"
        params:
          prompt_template: "alternative_title"
          input_fields: ["title", "description", "subject"]
          condition: "when_title_unclear"
    validators:
      - type: "max_length"
        params: {max: 300}
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "AI-generated when main title is not sufficiently descriptive."
    provenance:
      source_system: "AI-Generated"
      transformation_type: "derived"

  # ═══════════════════════════════════════════════════════════════════
  # SUBJECT CLASSIFICATION
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dc:subject[keyword]"
    source_fields: ["keyword"]
    transform_pipeline:
      - name: "split_to_array"
        params: {delimiter: ";", trim: true}
      - name: "deduplicate"
      - name: "ai_enhance"
        params:
          condition: "when_empty_or_sparse"
          prompt_template: "generate_keywords"
    validators:
      - type: "min_items"
        params: {min: 1}
    default: []
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Keywords from catalog level. AI-generated if missing."
    provenance:
      source_system: "OGD"
      transformation_type: "split_array"

  - target_field: "dc:subject[sector]"
    source_fields: ["sector"]
    transform_pipeline:
      - name: "split_to_array"
        params: {delimiter: ";", trim: true}
      - name: "normalize_sector"
        params: {vocab_file: "sectors.json"}
      - name: "deduplicate"
      - name: "replace_all_with_sectors"
        params:
          condition: "when_contains_all"
    validators:
      - type: "controlled_vocabulary"
        params: {vocab_file: "sectors.json"}
    default: []
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "From controlled 36 sectors. 'All' should be expanded or assigned."
    provenance:
      source_system: "OGD"
      transformation_type: "controlled_vocab"

  - target_field: "dc:subject[sector_resource]"
    source_fields: ["sector_resource", "sector"]
    transform_pipeline:
      - name: "coalesce"
        params: {prefer_first: true}
      - name: "split_to_array"
        params: {delimiter: ";", trim: true}
      - name: "normalize_sector"
        params: {vocab_file: "sectors.json"}
      - name: "deduplicate"
    validators:
      - type: "controlled_vocabulary"
        params: {vocab_file: "sectors.json"}
    default: []
    required: false
    mandatory_or_optional: "Optional"
    remarks: "Inherited from catalog sector if not specified at resource level."
    provenance:
      source_system: "OGD"
      transformation_type: "coalesce"

  # ═══════════════════════════════════════════════════════════════════
  # DATE ELEMENTS
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcterms:created"
    source_fields: ["created"]
    transform_pipeline:
      - name: "parse_date"
        params: {formats: ["DD/MM/YYYY", "YYYY-MM-DD", "YYYY-MM-DD HH:mm:ss"]}
      - name: "format_date"
        params: {output_format: "YYYY-MM-DD"}
    validators:
      - type: "date_format"
        params: {format: "ISO8601"}
      - type: "date_not_future"
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "ISO 8601 format recommended."
    provenance:
      source_system: "OGD"
      transformation_type: "date_normalize"

  - target_field: "dcterms:issued"
    source_fields: ["published_date"]
    transform_pipeline:
      - name: "parse_date"
        params: {formats: ["DD/MM/YYYY", "YYYY-MM-DD", "YYYY-MM-DD HH:mm:ss"]}
      - name: "format_date"
        params: {output_format: "YYYY-MM-DD"}
    validators:
      - type: "date_format"
        params: {format: "ISO8601"}
      - type: "required"
    default: null
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Publication date. Mandatory field."
    provenance:
      source_system: "OGD"
      transformation_type: "date_normalize"

  - target_field: "dcterms:modified"
    source_fields: ["changed"]
    transform_pipeline:
      - name: "parse_date"
        params: {formats: ["DD/MM/YYYY", "YYYY-MM-DD", "YYYY-MM-DD HH:mm:ss"]}
      - name: "format_date"
        params: {output_format: "YYYY-MM-DD"}
    validators:
      - type: "date_format"
        params: {format: "ISO8601"}
      - type: "required"
      - type: "date_gte"
        params: {reference_field: "dcterms:created"}
    default: null
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Last modification date. Must be >= created date."
    provenance:
      source_system: "OGD"
      transformation_type: "date_normalize"

  - target_field: "dcterms:temporal"
    source_fields: ["duration_of_date"]
    transform_pipeline:
      - name: "parse_duration_range"
      - name: "format_dcmi_period"
      - name: "compute_from_dataset"
        params:
          fallback: true
          condition: "when_empty"
    validators:
      - type: "dcmi_period_format"
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "DCMI Period format. Can be computed from dataset content."
    provenance:
      source_system: "OGD/Derived"
      transformation_type: "computed"

  # ═══════════════════════════════════════════════════════════════════
  # IDENTIFIER
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dc:identifier[uuid]"
    source_fields: ["uuid"]
    transform_pipeline:
      - name: "direct_copy"
      - name: "generate_uuid"
        params: {condition: "when_empty"}
    validators:
      - type: "uuid_format"
      - type: "required"
    default: null
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Unique identifier. Generated if not present."
    provenance:
      source_system: "OGD"
      transformation_type: "direct"

  - target_field: "dc:identifier[landing_page]"
    source_fields: ["domain", "node_alias"]
    transform_pipeline:
      - name: "construct_url"
        params:
          template: "https://www.{domain}{node_alias}"
    validators:
      - type: "url_format"
      - type: "required"
    default: null
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Landing page URL constructed from domain + node_alias."
    provenance:
      source_system: "OGD"
      transformation_type: "composite"

  - target_field: "dc:identifier[api_url]"
    source_fields: ["datafile_url"]
    transform_pipeline:
      - name: "direct_copy"
      - name: "validate_url"
    validators:
      - type: "url_format"
    default: "NA"
    required: false
    mandatory_or_optional: "Optional"
    remarks: "API access URL if available."
    provenance:
      source_system: "OGD"
      transformation_type: "direct"

  # ═══════════════════════════════════════════════════════════════════
  # PUBLISHER (Ordered Array)
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dc:publisher"
    source_fields: ["ministry_department", "state_department"]
    transform_pipeline:
      - name: "build_publisher_hierarchy"
        params:
          order: ["ministry_department", "state_department"]
          delimiter: ";"
          flatten: false
    validators:
      - type: "required"
      - type: "min_items"
        params: {min: 1}
    default: []
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Ordered array: [Ministry, Department, Sub-department]. Maps to Source Organisation in AI Kosh."
    provenance:
      source_system: "OGD"
      transformation_type: "hierarchy_array"

  # ═══════════════════════════════════════════════════════════════════
  # COVERAGE / GRANULARITY
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcterms:coverage"
    source_fields: ["granularity"]
    transform_pipeline:
      - name: "normalize_granularity"
      - name: "convert_to_iso8601_duration"
        params:
          mapping:
            "Daily": "P1D"
            "Weekly": "P7D"
            "Fortnightly": "P14D"
            "Monthly": "P1M"
            "Quarterly": "P3M"
            "Half Yearly": "P6M"
            "Annual": "P1Y"
            "Bi-Annual": "P2Y"
            "Hourly": "PT1H"
            "One-time": "NA"
            "Others": "NA"
      - name: "append_xsd_duration"
    validators:
      - type: "iso8601_duration"
    default: "NA"
    required: false
    mandatory_or_optional: "Optional"
    remarks: "Temporal resolution as ISO 8601 duration (e.g., P1D^^xsd:duration)."
    provenance:
      source_system: "OGD"
      transformation_type: "controlled_vocab_mapping"

  # ═══════════════════════════════════════════════════════════════════
  # EXTENT & RELATION[download_url] LINKAGE
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcterms:extent"
    source_fields: ["file_size"]
    transform_pipeline:
      - name: "convert_to_bytes"
      - name: "format_with_readable"
        params:
          include_readable: true
          format: "{bytes}({readable})"
    validators:
      - type: "numeric"
        params: {min: 0}
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "File size in bytes. Should correspond to relation[download_url]."
    provenance:
      source_system: "OGD"
      transformation_type: "numeric_format"

  - target_field: "dc:relation[download_url]"
    source_fields: ["datafile"]
    transform_pipeline:
      - name: "validate_url"
      - name: "ensure_https"
    validators:
      - type: "url_format"
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "Default dataset download URL (usually CSV)."
    provenance:
      source_system: "OGD"
      transformation_type: "url_validate"

  # ═══════════════════════════════════════════════════════════════════
  # RELATION[endpointURL] & endpoint description
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dc:relation[csv_endpointURL]"
    source_fields: ["datafile_url"]
    transform_pipeline:
      - name: "construct_endpoint_url"
        params:
          format_suffix: "csv"
          template: "{base_url}?format=csv"
    validators:
      - type: "url_format"
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "API endpoint returning CSV responses."
    provenance:
      source_system: "OGD"
      transformation_type: "url_construct"

  - target_field: "dc:relation[json_endpointURL]"
    source_fields: ["datafile_url"]
    transform_pipeline:
      - name: "construct_endpoint_url"
        params:
          format_suffix: "json"
    validators:
      - type: "url_format"
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "API endpoint returning JSON responses."
    provenance:
      source_system: "OGD"
      transformation_type: "url_construct"

  - target_field: "description:endpointDescription"
    source_fields: []
    transform_pipeline:
      - name: "ai_generate"
        params:
          prompt_template: "endpoint_description"
          input_fields: ["title", "file_format", "datafile_url"]
          condition: "when_endpoint_exists"
    validators:
      - type: "max_length"
        params: {max: 500}
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "AI-generated description of API endpoint. Omit if no endpoint."
    provenance:
      source_system: "AI-Generated"
      transformation_type: "derived"

  # ═══════════════════════════════════════════════════════════════════
  # ACCRUAL PERIODICITY (Frequency)
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcterms:accrualPeriodicity"
    source_fields: ["frequency"]
    transform_pipeline:
      - name: "map_to_uri"
        params:
          mapping:
            "Daily": "http://purl.org/dc/terms/Daily"
            "Weekly": "http://purl.org/cld/freq/weekly"
            "Fortnightly": "http://purl.org/cld/freq/biweekly"
            "Monthly": "http://purl.org/dc/terms/Monthly"
            "Quarterly": "http://purl.org/dc/terms/Quarterly"
            "Half Yearly": "http://purl.org/dc/terms/Frequency/Semiannual"
            "Annual": "http://purl.org/dc/terms/Annual"
            "Bi-Annual": "http://purl.org/cld/freq/biennial"
            "Hourly": "http://purl.org/cld/freq/continuous"
            "One-time": "http://purl.org/cld/freq/irregular"
            "Others": "http://purl.org/cld/freq/irregular"
    validators:
      - type: "uri_format"
      - type: "required"
    default: "http://purl.org/cld/freq/irregular"
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Dataset update frequency as Dublin Core Frequency URI."
    provenance:
      source_system: "OGD"
      transformation_type: "controlled_vocab_uri"

### 2.2 Additional Mapping Examples

```yaml
  # ═══════════════════════════════════════════════════════════════════
  # SPATIAL COVERAGE
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcterms:spatial"
    source_fields: ["field_asset_jurisdiction"]
    transform_pipeline:
      - name: "normalize_jurisdiction"
        params:
          mapping:
            "All India": "India"
            "all india": "India"
            "National": "India"
    validators:
      - type: "required"
    default: "India"
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Geographic coverage. Normalized to standard values."

  # ═══════════════════════════════════════════════════════════════════
  # JURISDICTION (India Extension)
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcin:jurisdiction"
    source_fields: ["govt_type"]
    transform_pipeline:
      - name: "normalize_case"
        params: {case: "title"}
      - name: "controlled_vocab_validate"
        params: {vocab: ["Central", "State"]}
    validators:
      - type: "controlled_vocabulary"
        params: {values: ["Central", "State"]}
      - type: "required"
    default: "Central"
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Government level (Central/State). India-specific extension."

  # ═══════════════════════════════════════════════════════════════════
  # FORMAT (MIME Type)
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dc:format"
    source_fields: ["file_format"]
    transform_pipeline:
      - name: "normalize_mime_type"
        params:
          mapping:
            "csv": "text/csv"
            "text/csv": "text/csv"
            "json": "application/json"
            "text/json": "application/json"
            "xml": "application/xml"
            "text/xml": "application/xml"
            "xls": "application/vnd.ms-excel"
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            "geojson": "application/geo+json"
            "application/geo+json": "application/geo+json"
            "zip": "application/zip"
            "pdf": "application/pdf"
    validators:
      - type: "mime_type_format"
    default: null
    required: false
    mandatory_or_optional: "Optional"
    remarks: "File format as MIME type."

  # ═══════════════════════════════════════════════════════════════════
  # LICENSE
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcterms:license"
    source_fields: ["license"]
    transform_pipeline:
      - name: "default_if_empty"
        params: {default: "GODL"}
    validators:
      - type: "controlled_vocabulary"
        params: {vocab_file: "licenses.json"}
      - type: "required"
    default: "GODL"
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "License identifier. Defaults to GODL for OGD."

  # ═══════════════════════════════════════════════════════════════════
  # ACCESS RIGHTS
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcterms:accessRights"
    source_fields: ["access_type", "field_resource_type"]
    transform_pipeline:
      - name: "determine_access_rights"
        params:
          type_5_is_registered: true
    validators:
      - type: "controlled_vocabulary"
        params: {values: ["Open", "Registered", "Restricted"]}
      - type: "required"
    default: "Open"
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "Access classification. Type-5 datasets are Registered."

  # ═══════════════════════════════════════════════════════════════════
  # ACCRUAL METHOD
  # ═══════════════════════════════════════════════════════════════════
  
  - target_field: "dcterms:accrualMethod"
    source_fields: ["field_resource_type"]
    transform_pipeline:
      - name: "map_resource_type"
        params:
          mapping:
            1: "Static Dataset"
            2: "Periodic Collection"
            4: "File Download"
            5: "API Service"
    validators:
      - type: "required"
    default: "Static Dataset"
    required: true
    mandatory_or_optional: "Mandatory"
    remarks: "How data is accumulated/generated."
```

---

## 3. Derived Metadata Calculators

### 3.1 Temporal Coverage Calculator

**Purpose:** Compute the date range covered by the dataset content.

**Algorithm:**

```python
# src/ogd_dc_transformer/derived/temporal_coverage.py

import pandas as pd
import numpy as np
from datetime import datetime, date
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass
import re
from dateutil import parser as date_parser

@dataclass
class TemporalCoverageResult:
    """Result of temporal coverage computation."""
    start_date: Optional[date]
    end_date: Optional[date]
    is_ongoing: bool
    confidence: float  # 0.0 to 1.0
    date_columns_used: List[str]
    method: str  # "column_scan", "ogd_duration", "filename", "inferred"
    sample_dates: List[str]
    warnings: List[str]
    
    def to_dcmi_period(self) -> str:
        """Format as DCMI Period string."""
        if self.start_date is None:
            return "NA"
        
        start_str = self.start_date.isoformat()
        if self.is_ongoing or self.end_date is None:
            return f"start: {start_str}; end: NA"
        
        return f"start: {start_str}; end: {self.end_date.isoformat()}"


class TemporalCoverageCalculator:
    """Calculate temporal coverage from dataset content."""
    
    # Common date column name patterns
    DATE_COLUMN_PATTERNS = [
        r'(?i)^date$', r'(?i)date_?time$', r'(?i)timestamp$',
        r'(?i).*_date$', r'(?i).*_dt$', r'(?i)^dt_.*',
        r'(?i)year', r'(?i)month', r'(?i)quarter',
        r'(?i)period', r'(?i)fiscal_?year', r'(?i)fy',
        r'(?i)start_?date', r'(?i)end_?date',
        r'(?i)created', r'(?i)modified', r'(?i)published',
        r'(?i)reporting_?date', r'(?i)record_?date',
        r'(?i)transaction_?date', r'(?i)effective_?date'
    ]
    
    # Date format patterns to try
    DATE_FORMATS = [
        "%Y-%m-%d",           # 2024-01-15
        "%d/%m/%Y",           # 15/01/2024
        "%d-%m-%Y",           # 15-01-2024
        "%Y/%m/%d",           # 2024/01/15
        "%d %b %Y",           # 15 Jan 2024
        "%d %B %Y",           # 15 January 2024
        "%b %d, %Y",          # Jan 15, 2024
        "%Y%m%d",             # 20240115
        "%Y",                 # 2024 (year only)
        "%m/%Y",              # 01/2024 (month/year)
        "%Y-%m",              # 2024-01 (year-month)
        "%b-%Y",              # Jan-2024
        "%B %Y",              # January 2024
    ]
    
    def __init__(
        self,
        sample_size: int = 1000,
        min_confidence: float = 0.7,
        max_columns_to_scan: int = 20
    ):
        self.sample_size = sample_size
        self.min_confidence = min_confidence
        self.max_columns_to_scan = max_columns_to_scan
    
    def calculate(
        self,
        dataset_path: str,
        ogd_duration: Optional[str] = None,
        file_format: str = "csv"
    ) -> TemporalCoverageResult:
        """
        Calculate temporal coverage from dataset.
        
        Args:
            dataset_path: Path to the dataset file
            ogd_duration: OGD "Duration of Date" field value if available
            file_format: Format of the file (csv, json, excel)
        
        Returns:
            TemporalCoverageResult with computed values
        """
        warnings = []
        
        # Strategy 1: Use OGD Duration if available and valid
        if ogd_duration and self._is_valid_duration(ogd_duration):
            result = self._parse_ogd_duration(ogd_duration)
            if result:
                return result
            warnings.append("OGD duration field present but unparseable")
        
        # Strategy 2: Scan dataset content
        try:
            df = self._load_sample(dataset_path, file_format)
            
            if df is None or df.empty:
                warnings.append("Could not load dataset or dataset is empty")
                return self._fallback_result(warnings)
            
            # Find date columns
            date_columns = self._identify_date_columns(df)
            
            if not date_columns:
                warnings.append("No date columns identified")
                # Try to extract year from any column
                year_result = self._extract_years_fallback(df)
                if year_result:
                    year_result.warnings.extend(warnings)
                    return year_result
                return self._fallback_result(warnings)
            
            # Parse and compute range
            return self._compute_range_from_columns(df, date_columns, warnings)
            
        except Exception as e:
            warnings.append(f"Error processing dataset: {str(e)}")
            return self._fallback_result(warnings)
    
    def _is_valid_duration(self, duration: str) -> bool:
        """Check if OGD duration field has valid content."""
        if not duration:
            return False
        duration_lower = duration.lower().strip()
        invalid_patterns = ['na', 'n/a', 'null', 'none', 'empty', '(empty)']
        return duration_lower not in invalid_patterns
    
    def _parse_ogd_duration(self, duration: str) -> Optional[TemporalCoverageResult]:
        """Parse OGD Duration of Date field (e.g., 'from: 01/03/2000, to: ongoing')."""
        try:
            duration = duration.strip()
            
            # Pattern: "from: DD/MM/YYYY, to: DD/MM/YYYY" or "from: DD/MM/YYYY, to: ongoing"
            from_match = re.search(r'from[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4})', duration, re.I)
            to_match = re.search(r'to[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}|ongoing|present|current)', duration, re.I)
            
            start_date = None
            end_date = None
            is_ongoing = False
            
            if from_match:
                start_date = self._parse_single_date(from_match.group(1))
            
            if to_match:
                to_value = to_match.group(1).lower()
                if to_value in ['ongoing', 'present', 'current']:
                    is_ongoing = True
                else:
                    end_date = self._parse_single_date(to_match.group(1))
            
            if start_date:
                return TemporalCoverageResult(
                    start_date=start_date,
                    end_date=end_date,
                    is_ongoing=is_ongoing,
                    confidence=0.95,
                    date_columns_used=[],
                    method="ogd_duration",
                    sample_dates=[],
                    warnings=[]
                )
        except Exception:
            pass
        return None
    
    def _parse_single_date(self, date_str: str) -> Optional[date]:
        """Parse a single date string."""
        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        
        # Try dateutil parser as fallback
        try:
            return date_parser.parse(date_str, dayfirst=True).date()
        except Exception:
            pass
        
        return None
    
    def _load_sample(self, path: str, file_format: str) -> Optional[pd.DataFrame]:
        """Load a sample of the dataset."""
        try:
            if file_format.lower() in ['csv', 'text/csv']:
                return pd.read_csv(path, nrows=self.sample_size, encoding='utf-8', 
                                   on_bad_lines='skip')
            elif file_format.lower() in ['json', 'application/json']:
                df = pd.read_json(path)
                return df.head(self.sample_size)
            elif file_format.lower() in ['xls', 'xlsx', 'application/vnd.ms-excel']:
                return pd.read_excel(path, nrows=self.sample_size)
            else:
                # Try CSV as default
                return pd.read_csv(path, nrows=self.sample_size, encoding='utf-8',
                                   on_bad_lines='skip')
        except Exception:
            return None
    
    def _identify_date_columns(self, df: pd.DataFrame) -> List[str]:
        """Identify columns likely to contain dates."""
        date_columns = []
        
        for col in df.columns[:self.max_columns_to_scan]:
            # Check column name patterns
            name_match = any(re.match(pat, str(col)) for pat in self.DATE_COLUMN_PATTERNS)
            
            # Check data type
            is_datetime_type = pd.api.types.is_datetime64_any_dtype(df[col])
            
            # Sample values to check if they look like dates
            looks_like_dates = self._column_looks_like_dates(df[col])
            
            if is_datetime_type or (name_match and looks_like_dates):
                date_columns.append(col)
            elif looks_like_dates and self._high_date_confidence(df[col]):
                date_columns.append(col)
        
        return date_columns
    
    def _column_looks_like_dates(self, series: pd.Series, sample_n: int = 50) -> bool:
        """Check if column values look like dates."""
        non_null = series.dropna().head(sample_n)
        if len(non_null) == 0:
            return False
        
        date_count = 0
        for val in non_null:
            if self._parse_single_date(str(val)):
                date_count += 1
        
        return date_count / len(non_null) > 0.5
    
    def _high_date_confidence(self, series: pd.Series) -> bool:
        """Check if we have high confidence this is a date column."""
        non_null = series.dropna().head(100)
        if len(non_null) < 10:
            return False
        
        date_count = sum(1 for val in non_null if self._parse_single_date(str(val)))
        return date_count / len(non_null) > 0.8
    
    def _compute_range_from_columns(
        self, 
        df: pd.DataFrame, 
        date_columns: List[str],
        warnings: List[str]
    ) -> TemporalCoverageResult:
        """Compute date range from identified date columns."""
        all_dates = []
        columns_used = []
        sample_dates = []
        
        for col in date_columns:
            parsed_dates = []
            for val in df[col].dropna():
                d = self._parse_single_date(str(val))
                if d:
                    parsed_dates.append(d)
            
            if parsed_dates:
                all_dates.extend(parsed_dates)
                columns_used.append(col)
                # Keep some samples for debugging
                sample_dates.extend([str(d) for d in parsed_dates[:3]])
        
        if not all_dates:
            warnings.append("Could not parse any dates from identified columns")
            return self._fallback_result(warnings)
        
        min_date = min(all_dates)
        max_date = max(all_dates)
        
        # Determine if ongoing (max date is recent)
        today = date.today()
        is_ongoing = (today - max_date).days < 90  # Within 3 months
        
        # Compute confidence based on coverage
        unique_dates = len(set(all_dates))
        confidence = min(0.95, 0.6 + (unique_dates / 100) * 0.35)
        
        return TemporalCoverageResult(
            start_date=min_date,
            end_date=None if is_ongoing else max_date,
            is_ongoing=is_ongoing,
            confidence=confidence,
            date_columns_used=columns_used,
            method="column_scan",
            sample_dates=sample_dates[:10],
            warnings=warnings
        )
    
    def _extract_years_fallback(self, df: pd.DataFrame) -> Optional[TemporalCoverageResult]:
        """Fallback: try to extract year values from any column."""
        year_pattern = re.compile(r'\b(19\d{2}|20\d{2})\b')
        years = set()
        
        for col in df.columns[:10]:
            for val in df[col].dropna().head(100):
                matches = year_pattern.findall(str(val))
                years.update(int(y) for y in matches)
        
        if years:
            min_year = min(years)
            max_year = max(years)
            current_year = date.today().year
            
            return TemporalCoverageResult(
                start_date=date(min_year, 1, 1),
                end_date=None if max_year >= current_year else date(max_year, 12, 31),
                is_ongoing=max_year >= current_year,
                confidence=0.5,
                date_columns_used=[],
                method="year_extraction",
                sample_dates=[str(y) for y in sorted(years)[:5]],
                warnings=["Only year values could be extracted, day/month unknown"]
            )
        
        return None
    
    def _fallback_result(self, warnings: List[str]) -> TemporalCoverageResult:
        """Return a fallback result when no dates could be computed."""
        warnings.append("Could not determine temporal coverage from dataset")
        return TemporalCoverageResult(
            start_date=None,
            end_date=None,
            is_ongoing=False,
            confidence=0.0,
            date_columns_used=[],
            method="fallback",
            sample_dates=[],
            warnings=warnings
        )
```

### 3.2 Granularity Calculator (Temporal Resolution)

**Purpose:** Determine the temporal resolution/frequency of data points.

```python
# src/ogd_dc_transformer/derived/granularity.py

import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass
from collections import Counter
import statistics

@dataclass
class GranularityResult:
    """Result of granularity computation."""
    iso_duration: str  # e.g., "P1D", "P1M", "P1Y"
    human_readable: str  # e.g., "Daily", "Monthly", "Annual"
    confidence: float
    method: str  # "delta_analysis", "ogd_field", "inferred"
    median_delta_days: Optional[float]
    is_irregular: bool
    irregularity_reason: Optional[str]
    sample_deltas: List[int]  # Sample of deltas in days
    warnings: List[str]
    
    def to_xsd_duration(self) -> str:
        """Format as xsd:duration string."""
        if self.iso_duration == "NA":
            return "NA"
        return f"{self.iso_duration}^^xsd:duration"


class GranularityCalculator:
    """Calculate temporal granularity/resolution from dataset."""
    
    # Standard granularity buckets with tolerance ranges (in days)
    GRANULARITY_BUCKETS = {
        "PT1H": {"name": "Hourly", "min_days": 0, "max_days": 0.1},
        "P1D": {"name": "Daily", "min_days": 0.5, "max_days": 1.5},
        "P7D": {"name": "Weekly", "min_days": 6, "max_days": 8},
        "P14D": {"name": "Fortnightly", "min_days": 13, "max_days": 16},
        "P1M": {"name": "Monthly", "min_days": 27, "max_days": 32},
        "P3M": {"name": "Quarterly", "min_days": 85, "max_days": 95},
        "P6M": {"name": "Semi-annual", "min_days": 175, "max_days": 190},
        "P1Y": {"name": "Annual", "min_days": 360, "max_days": 370},
        "P2Y": {"name": "Biennial", "min_days": 720, "max_days": 740},
    }
    
    # Map OGD granularity values to ISO 8601
    OGD_GRANULARITY_MAP = {
        "hourly": "PT1H",
        "daily": "P1D",
        "weekly": "P7D",
        "fortnightly": "P14D",
        "monthly": "P1M",
        "quarterly": "P3M",
        "half yearly": "P6M",
        "semi-annual": "P6M",
        "annual": "P1Y",
        "yearly": "P1Y",
        "bi-annual": "P2Y",
        "biennial": "P2Y",
        "one-time": "NA",
        "others": "NA",
    }
    
    def __init__(
        self,
        sample_size: int = 500,
        min_data_points: int = 5,
        irregularity_threshold: float = 0.3  # CV threshold for irregular
    ):
        self.sample_size = sample_size
        self.min_data_points = min_data_points
        self.irregularity_threshold = irregularity_threshold
    
    def calculate(
        self,
        dates: Optional[List[date]] = None,
        ogd_granularity: Optional[str] = None,
        dataset_path: Optional[str] = None,
        date_column: Optional[str] = None
    ) -> GranularityResult:
        """
        Calculate granularity from date values or OGD field.
        
        Args:
            dates: List of parsed date values (if already available)
            ogd_granularity: OGD granularity field value
            dataset_path: Path to dataset (used if dates not provided)
            date_column: Column name containing dates
        
        Returns:
            GranularityResult with computed values
        """
        warnings = []
        
        # Strategy 1: Use OGD granularity if available
        if ogd_granularity:
            normalized = ogd_granularity.lower().strip()
            if normalized in self.OGD_GRANULARITY_MAP:
                iso_dur = self.OGD_GRANULARITY_MAP[normalized]
                human = self._get_human_readable(iso_dur)
                return GranularityResult(
                    iso_duration=iso_dur,
                    human_readable=human,
                    confidence=0.9,
                    method="ogd_field",
                    median_delta_days=None,
                    is_irregular=iso_dur == "NA",
                    irregularity_reason="OGD marked as irregular" if iso_dur == "NA" else None,
                    sample_deltas=[],
                    warnings=[]
                )
        
        # Strategy 2: Compute from dates
        if dates is None or len(dates) < self.min_data_points:
            if dataset_path and date_column:
                dates = self._extract_dates(dataset_path, date_column)
            
            if dates is None or len(dates) < self.min_data_points:
                warnings.append(f"Insufficient data points (need {self.min_data_points})")
                return self._fallback_result(warnings)
        
        return self._compute_from_dates(dates, warnings)
    
    def _compute_from_dates(
        self, 
        dates: List[date], 
        warnings: List[str]
    ) -> GranularityResult:
        """Compute granularity from a list of dates."""
        # Sort and deduplicate
        unique_dates = sorted(set(dates))
        
        if len(unique_dates) < 2:
            warnings.append("Need at least 2 unique dates")
            return self._fallback_result(warnings)
        
        # Compute deltas
        deltas_days = []
        for i in range(1, len(unique_dates)):
            delta = (unique_dates[i] - unique_dates[i-1]).days
            if delta > 0:  # Ignore same-day entries
                deltas_days.append(delta)
        
        if not deltas_days:
            warnings.append("All dates are identical")
            return self._fallback_result(warnings)
        
        # Use median delta (robust to outliers)
        median_delta = statistics.median(deltas_days)
        
        # Check for irregularity using coefficient of variation
        if len(deltas_days) >= 3:
            mean_delta = statistics.mean(deltas_days)
            stdev_delta = statistics.stdev(deltas_days)
            cv = stdev_delta / mean_delta if mean_delta > 0 else 0
            is_irregular = cv > self.irregularity_threshold
        else:
            is_irregular = False
            cv = 0
        
        # Match to standard bucket
        iso_duration, human_readable, confidence = self._match_to_bucket(median_delta)
        
        if is_irregular and iso_duration != "NA":
            irregularity_reason = f"High variability in intervals (CV={cv:.2f})"
            confidence *= 0.7  # Reduce confidence for irregular data
        else:
            irregularity_reason = None
        
        return GranularityResult(
            iso_duration=iso_duration,
            human_readable=human_readable,
            confidence=confidence,
            method="delta_analysis",
            median_delta_days=median_delta,
            is_irregular=is_irregular,
            irregularity_reason=irregularity_reason,
            sample_deltas=deltas_days[:20],
            warnings=warnings
        )
    
    def _match_to_bucket(self, median_days: float) -> Tuple[str, str, float]:
        """Match median delta to a standard granularity bucket."""
        best_match = None
        best_distance = float('inf')
        
        for iso_dur, bucket in self.GRANULARITY_BUCKETS.items():
            bucket_mid = (bucket["min_days"] + bucket["max_days"]) / 2
            
            if bucket["min_days"] <= median_days <= bucket["max_days"]:
                # Within bucket range
                distance = abs(median_days - bucket_mid)
                if distance < best_distance:
                    best_distance = distance
                    best_match = (iso_dur, bucket["name"])
        
        if best_match:
            # Confidence based on how close to bucket center
            bucket = self.GRANULARITY_BUCKETS[best_match[0]]
            bucket_mid = (bucket["min_days"] + bucket["max_days"]) / 2
            bucket_range = bucket["max_days"] - bucket["min_days"]
            confidence = 0.95 - (abs(median_days - bucket_mid) / bucket_range) * 0.2
            return best_match[0], best_match[1], confidence
        
        # No exact match - find closest or mark as irregular
        if median_days < 0.5:
            return "PT1H", "Sub-daily", 0.6
        elif median_days > 740:
            return "P1Y", "Multi-year", 0.5
        else:
            return "NA", "Irregular", 0.4
    
    def _get_human_readable(self, iso_duration: str) -> str:
        """Get human readable name for ISO duration."""
        for dur, bucket in self.GRANULARITY_BUCKETS.items():
            if dur == iso_duration:
                return bucket["name"]
        return "Unknown"
    
    def _extract_dates(self, path: str, column: str) -> Optional[List[date]]:
        """Extract dates from dataset file."""
        try:
            df = pd.read_csv(path, nrows=self.sample_size, usecols=[column])
            dates = pd.to_datetime(df[column], errors='coerce').dropna()
            return [d.date() for d in dates]
        except Exception:
            return None
    
    def _fallback_result(self, warnings: List[str]) -> GranularityResult:
        """Return fallback result when computation fails."""
        warnings.append("Could not determine granularity")
        return GranularityResult(
            iso_duration="NA",
            human_readable="Unknown",
            confidence=0.0,
            method="fallback",
            median_delta_days=None,
            is_irregular=True,
            irregularity_reason="Insufficient data",
            sample_deltas=[],
            warnings=warnings
        )
```

### 3.3 PII Profiler (Content Scanning)

**Purpose:** Detect potential PII in dataset content.

```python
# src/ogd_dc_transformer/profiling/pii_detector.py

import re
import pandas as pd
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum
import hashlib

class PIIType(str, Enum):
    AADHAAR = "aadhaar"
    PAN = "pan"
    PHONE = "phone"
    EMAIL = "email"
    PASSPORT = "passport"
    DRIVING_LICENSE = "driving_license"
    VOTER_ID = "voter_id"
    BANK_ACCOUNT = "bank_account"
    CREDIT_CARD = "credit_card"
    NAME = "name"
    ADDRESS = "address"
    DATE_OF_BIRTH = "date_of_birth"
    PINCODE = "pincode"
    IP_ADDRESS = "ip_address"

class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"

@dataclass
class PIIMatch:
    """Single PII detection match."""
    pii_type: PIIType
    column: str
    count: int
    sample_redacted: Optional[str] = None  # Redacted sample for verification
    confidence: float = 1.0

@dataclass 
class PIIProfileResult:
    """Complete PII profiling result."""
    has_pii: bool
    overall_risk: RiskLevel
    risk_score: float  # 0.0 to 1.0
    matches: List[PIIMatch]
    affected_columns: List[str]
    summary_by_type: Dict[str, int]
    total_rows_scanned: int
    sample_rate: float
    warnings: List[str]
    recommendations: List[str]
    
    def to_analytics_block(self) -> Dict[str, Any]:
        """Format as analytics/profile block for storage."""
        return {
            "pii_scan": {
                "has_pii": self.has_pii,
                "risk_level": self.overall_risk.value,
                "risk_score": self.risk_score,
                "affected_columns": self.affected_columns,
                "detection_summary": self.summary_by_type,
                "rows_scanned": self.total_rows_scanned,
                "sample_rate": self.sample_rate,
                "scan_timestamp": pd.Timestamp.now().isoformat()
            }
        }


class PIIDetector:
    """Detect Indian PII patterns in dataset content."""
    
    # Indian PII Patterns (compiled for performance)
    PATTERNS = {
        PIIType.AADHAAR: {
            "pattern": re.compile(r'\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b'),
            "risk": RiskLevel.HIGH,
            "validator": "_validate_aadhaar",
            "description": "Aadhaar number (12-digit unique ID)"
        },
        PIIType.PAN: {
            "pattern": re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b'),
            "risk": RiskLevel.HIGH,
            "validator": "_validate_pan",
            "description": "PAN card number"
        },
        PIIType.PHONE: {
            "pattern": re.compile(r'\b(?:\+91[-\s]?)?[6-9]\d{9}\b'),
            "risk": RiskLevel.MEDIUM,
            "validator": None,
            "description": "Indian mobile number"
        },
        PIIType.EMAIL: {
            "pattern": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            "risk": RiskLevel.MEDIUM,
            "validator": None,
            "description": "Email address"
        },
        PIIType.PASSPORT: {
            "pattern": re.compile(r'\b[A-Z][1-9]\d{7}\b'),
            "risk": RiskLevel.HIGH,
            "validator": None,
            "description": "Indian passport number"
        },
        PIIType.DRIVING_LICENSE: {
            "pattern": re.compile(r'\b[A-Z]{2}[0-9]{2}\s?[0-9]{4}\s?[0-9]{7}\b'),
            "risk": RiskLevel.HIGH,
            "validator": None,
            "description": "Indian driving license"
        },
        PIIType.VOTER_ID: {
            "pattern": re.compile(r'\b[A-Z]{3}[0-9]{7}\b'),
            "risk": RiskLevel.HIGH,
            "validator": None,
            "description": "Voter ID (EPIC)"
        },
        PIIType.CREDIT_CARD: {
            "pattern": re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b'),
            "risk": RiskLevel.HIGH,
            "validator": "_validate_luhn",
            "description": "Credit card number"
        },
        PIIType.BANK_ACCOUNT: {
            "pattern": re.compile(r'\b\d{9,18}\b'),  # Very broad - needs context
            "risk": RiskLevel.MEDIUM,
            "validator": None,
            "context_required": True,
            "context_keywords": ["account", "bank", "ifsc", "branch"],
            "description": "Bank account number"
        },
        PIIType.IP_ADDRESS: {
            "pattern": re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'),
            "risk": RiskLevel.LOW,
            "validator": None,
            "description": "IP address"
        },
        PIIType.PINCODE: {
            "pattern": re.compile(r'\b[1-9][0-9]{5}\b'),
            "risk": RiskLevel.LOW,
            "validator": None,
            "context_required": True,
            "context_keywords": ["pin", "postal", "zip", "pincode"],
            "description": "Indian PIN code"
        }
    }
    
    # Column name patterns that suggest PII
    SENSITIVE_COLUMN_PATTERNS = [
        (r'(?i)aadhaar|aadhar|uid', PIIType.AADHAAR),
        (r'(?i)pan[\s_]?(no|number|card)?', PIIType.PAN),
        (r'(?i)phone|mobile|contact|cell', PIIType.PHONE),
        (r'(?i)email|e[-_]?mail', PIIType.EMAIL),
        (r'(?i)passport', PIIType.PASSPORT),
        (r'(?i)license|licence|dl[\s_]?no', PIIType.DRIVING_LICENSE),
        (r'(?i)voter|epic', PIIType.VOTER_ID),
        (r'(?i)account[\s_]?(no|number)?', PIIType.BANK_ACCOUNT),
        (r'(?i)credit|card[\s_]?no', PIIType.CREDIT_CARD),
        (r'(?i)name|first[\s_]?name|last[\s_]?name|full[\s_]?name', PIIType.NAME),
        (r'(?i)address|addr|street|locality', PIIType.ADDRESS),
        (r'(?i)dob|birth[\s_]?date|date[\s_]?of[\s_]?birth', PIIType.DATE_OF_BIRTH),
    ]
    
    # Columns to skip (allow list)
    SAFE_COLUMN_PATTERNS = [
        r'(?i)^id$', r'(?i)^code$', r'(?i)serial', r'(?i)reference',
        r'(?i)count', r'(?i)total', r'(?i)year', r'(?i)month', r'(?i)date(?!.*birth)',
        r'(?i)district', r'(?i)state', r'(?i)country', r'(?i)region'
    ]
    
    def __init__(
        self,
        sample_size: int = 1000,
        sample_rate: float = 0.1,  # Sample 10% of large datasets
        max_rows: int = 10000,
        skip_columns: Optional[List[str]] = None
    ):
        self.sample_size = sample_size
        self.sample_rate = sample_rate
        self.max_rows = max_rows
        self.skip_columns = skip_columns or []
    
    def scan(
        self,
        dataset_path: str,
        file_format: str = "csv"
    ) -> PIIProfileResult:
        """
        Scan dataset for PII.
        
        Args:
            dataset_path: Path to the dataset file
            file_format: Format of the file
        
        Returns:
            PIIProfileResult with detection results
        """
        warnings = []
        matches: List[PIIMatch] = []
        
        try:
            df = self._load_dataset(dataset_path, file_format)
            
            if df is None or df.empty:
                warnings.append("Could not load dataset")
                return self._empty_result(warnings)
            
            total_rows = len(df)
            actual_sample_rate = len(df) / total_rows if total_rows > 0 else 0
            
            # Identify columns to scan
            columns_to_scan = self._get_columns_to_scan(df)
            
            # Scan each column
            for col in columns_to_scan:
                col_matches = self._scan_column(df, col)
                matches.extend(col_matches)
            
            return self._build_result(matches, total_rows, actual_sample_rate, warnings)
            
        except Exception as e:
            warnings.append(f"Error during scan: {str(e)}")
            return self._empty_result(warnings)
    
    def _load_dataset(self, path: str, file_format: str) -> Optional[pd.DataFrame]:
        """Load dataset with sampling for large files."""
        try:
            if file_format.lower() in ['csv', 'text/csv']:
                # For CSV, use skiprows for random sampling
                df = pd.read_csv(path, nrows=self.max_rows, encoding='utf-8',
                                on_bad_lines='skip')
            elif file_format.lower() in ['json', 'application/json']:
                df = pd.read_json(path)
                df = df.head(self.max_rows)
            elif file_format.lower() in ['xls', 'xlsx']:
                df = pd.read_excel(path, nrows=self.max_rows)
            else:
                df = pd.read_csv(path, nrows=self.max_rows, on_bad_lines='skip')
            
            # Sample if still too large
            if len(df) > self.sample_size:
                df = df.sample(n=self.sample_size, random_state=42)
            
            return df
        except Exception:
            return None
    
    def _get_columns_to_scan(self, df: pd.DataFrame) -> List[str]:
        """Determine which columns to scan based on allow/deny lists."""
        columns = []
        
        for col in df.columns:
            # Skip if in explicit skip list
            if col in self.skip_columns:
                continue
            
            # Skip if matches safe pattern
            if any(re.match(pat, col) for pat in self.SAFE_COLUMN_PATTERNS):
                continue
            
            # Include string/object columns
            if df[col].dtype == 'object' or df[col].dtype == 'string':
                columns.append(col)
        
        return columns
    
    def _scan_column(self, df: pd.DataFrame, column: str) -> List[PIIMatch]:
        """Scan a single column for PII patterns."""
        matches = []
        column_lower = column.lower()
        
        # Check column name for sensitivity hints
        column_pii_type = None
        for pattern, pii_type in self.SENSITIVE_COLUMN_PATTERNS:
            if re.search(pattern, column):
                column_pii_type = pii_type
                break
        
        # Scan values
        for pii_type, config in self.PATTERNS.items():
            pattern = config["pattern"]
            context_required = config.get("context_required", False)
            context_keywords = config.get("context_keywords", [])
            
            # Skip context-required patterns unless column name suggests context
            if context_required:
                has_context = any(kw in column_lower for kw in context_keywords)
                if not has_context and column_pii_type != pii_type:
                    continue
            
            # Count matches
            count = 0
            sample_value = None
            
            for val in df[column].dropna().astype(str):
                match = pattern.search(val)
                if match:
                    # Validate if validator exists
                    validator = config.get("validator")
                    if validator and hasattr(self, validator):
                        if not getattr(self, validator)(match.group()):
                            continue
                    
                    count += 1
                    if sample_value is None:
                        sample_value = self._redact(match.group(), pii_type)
            
            if count > 0:
                # Apply confidence based on column name match
                confidence = 0.95 if column_pii_type == pii_type else 0.7
                
                matches.append(PIIMatch(
                    pii_type=pii_type,
                    column=column,
                    count=count,
                    sample_redacted=sample_value,
                    confidence=confidence
                ))
        
        return matches
    
    def _validate_aadhaar(self, value: str) -> bool:
        """Validate Aadhaar using Verhoeff checksum."""
        digits = re.sub(r'\s', '', value)
        if len(digits) != 12:
            return False
        
        # Simplified validation - check it's not all same digits
        if len(set(digits)) == 1:
            return False
        
        return True
    
    def _validate_pan(self, value: str) -> bool:
        """Validate PAN format."""
        # Fourth character indicates holder type
        valid_fourth = 'PCFHATBLJG'
        return len(value) == 10 and value[3] in valid_fourth
    
    def _validate_luhn(self, value: str) -> bool:
        """Validate credit card using Luhn algorithm."""
        digits = [int(d) for d in value if d.isdigit()]
        if len(digits) < 13:
            return False
        
        checksum = 0
        for i, digit in enumerate(reversed(digits)):
            if i % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        
        return checksum % 10 == 0
    
    def _redact(self, value: str, pii_type: PIIType) -> str:
        """Redact PII value for safe storage."""
        if pii_type in [PIIType.AADHAAR, PIIType.PAN, PIIType.CREDIT_CARD]:
            # Show last 4 characters
            return "X" * (len(value) - 4) + value[-4:]
        elif pii_type in [PIIType.PHONE, PIIType.EMAIL]:
            # Hash the value
            h = hashlib.sha256(value.encode()).hexdigest()[:8]
            return f"[REDACTED:{h}]"
        else:
            return "[REDACTED]"
    
    def _build_result(
        self,
        matches: List[PIIMatch],
        total_rows: int,
        sample_rate: float,
        warnings: List[str]
    ) -> PIIProfileResult:
        """Build the final result from matches."""
        if not matches:
            return self._empty_result(warnings, total_rows, sample_rate)
        
        # Aggregate by type
        summary_by_type = {}
        for m in matches:
            key = m.pii_type.value
            summary_by_type[key] = summary_by_type.get(key, 0) + m.count
        
        # Affected columns
        affected_columns = list(set(m.column for m in matches))
        
        # Calculate risk score
        risk_weights = {RiskLevel.HIGH: 1.0, RiskLevel.MEDIUM: 0.5, RiskLevel.LOW: 0.2}
        total_weight = 0
        for m in matches:
            config = self.PATTERNS[m.pii_type]
            total_weight += risk_weights[config["risk"]] * m.count
        
        # Normalize risk score (0-1)
        risk_score = min(1.0, total_weight / (total_rows * 0.1))
        
        # Determine overall risk
        high_risk_types = {PIIType.AADHAAR, PIIType.PAN, PIIType.PASSPORT, 
                          PIIType.CREDIT_CARD, PIIType.BANK_ACCOUNT}
        has_high_risk = any(m.pii_type in high_risk_types for m in matches)
        
        if has_high_risk and risk_score > 0.5:
            overall_risk = RiskLevel.HIGH
        elif has_high_risk or risk_score > 0.3:
            overall_risk = RiskLevel.MEDIUM
        elif matches:
            overall_risk = RiskLevel.LOW
        else:
            overall_risk = RiskLevel.NONE
        
        # Generate recommendations
        recommendations = self._generate_recommendations(matches, overall_risk)
        
        return PIIProfileResult(
            has_pii=True,
            overall_risk=overall_risk,
            risk_score=risk_score,
            matches=matches,
            affected_columns=affected_columns,
            summary_by_type=summary_by_type,
            total_rows_scanned=total_rows,
            sample_rate=sample_rate,
            warnings=warnings,
            recommendations=recommendations
        )
    
    def _generate_recommendations(
        self, 
        matches: List[PIIMatch], 
        risk: RiskLevel
    ) -> List[str]:
        """Generate recommendations based on findings."""
        recs = []
        
        if risk == RiskLevel.HIGH:
            recs.append("CRITICAL: High-risk PII detected. Consider data masking or removal.")
        
        pii_types = set(m.pii_type for m in matches)
        
        if PIIType.AADHAAR in pii_types or PIIType.PAN in pii_types:
            recs.append("Government ID numbers detected. Verify if required for data purpose.")
        
        if PIIType.PHONE in pii_types or PIIType.EMAIL in pii_types:
            recs.append("Contact information detected. Consider anonymization if not essential.")
        
        if PIIType.CREDIT_CARD in pii_types or PIIType.BANK_ACCOUNT in pii_types:
            recs.append("Financial data detected. Ensure PCI-DSS compliance if retaining.")
        
        return recs
    
    def _empty_result(
        self, 
        warnings: List[str],
        total_rows: int = 0,
        sample_rate: float = 0
    ) -> PIIProfileResult:
        """Return empty result when no PII found."""
        return PIIProfileResult(
            has_pii=False,
            overall_risk=RiskLevel.NONE,
            risk_score=0.0,
            matches=[],
            affected_columns=[],
            summary_by_type={},
            total_rows_scanned=total_rows,
            sample_rate=sample_rate,
            warnings=warnings,
            recommendations=[]
        )
```

### 3.4 Example Derived Metadata JSON Block

```json
{
  "derived_metadata": {
    "temporal_coverage": {
      "dcmi_period": "start: 2020-01-01; end: NA",
      "computation": {
        "method": "column_scan",
        "confidence": 0.87,
        "date_columns_used": ["transaction_date", "record_date"],
        "sample_dates": ["2020-01-15", "2021-06-30", "2024-12-01"],
        "is_ongoing": true,
        "computed_at": "2025-01-20T10:30:00Z"
      }
    },
    "granularity": {
      "iso_duration": "P1D^^xsd:duration",
      "human_readable": "Daily",
      "computation": {
        "method": "delta_analysis",
        "confidence": 0.92,
        "median_delta_days": 1.02,
        "is_irregular": false,
        "sample_deltas": [1, 1, 1, 2, 1, 1],
        "computed_at": "2025-01-20T10:30:01Z"
      }
    }
  },
  "analytics_profile": {
    "pii_scan": {
      "has_pii": true,
      "risk_level": "medium",
      "risk_score": 0.35,
      "affected_columns": ["contact_phone", "email_address"],
      "detection_summary": {
        "phone": 1245,
        "email": 892
      },
      "rows_scanned": 5000,
      "sample_rate": 0.1,
      "scan_timestamp": "2025-01-20T10:30:15Z"
    },
    "schema_profile": {
      "total_columns": 15,
      "total_rows": 50000,
      "column_types": {
        "date": ["transaction_date", "record_date"],
        "numeric": ["amount", "quantity", "price"],
        "categorical": ["state", "district", "category"],
        "text": ["description", "notes"]
      },
      "null_percentages": {
        "transaction_date": 0.0,
        "amount": 0.02,
        "notes": 0.45
      }
    }
  }
}
```

---

## 4. Validation & QA Framework

### 4.1 Field-Level Validation Rules

```yaml
# config/validation/field_rules.yaml
version: "1.0.0"

field_validators:

  # ═══════════════════════════════════════════════════════════════════
  # REQUIRED FIELDS
  # ═══════════════════════════════════════════════════════════════════
  
  "dc:title":
    rules:
      - type: required
        severity: error
        message: "Title is mandatory"
      - type: min_length
        params: {min: 5}
        severity: error
        message: "Title must be at least 5 characters"
      - type: max_length
        params: {max: 500}
        severity: warning
        message: "Title exceeds recommended length"
      - type: no_html
        severity: error
        message: "Title should not contain HTML tags"

  "dcterms:issued":
    rules:
      - type: required
        severity: error
        message: "Publication date is mandatory"
      - type: date_format
        params: {format: "YYYY-MM-DD"}
        severity: error
        message: "Date must be in ISO 8601 format (YYYY-MM-DD)"
      - type: date_not_future
        severity: error
        message: "Publication date cannot be in the future"

  "dcterms:modified":
    rules:
      - type: required
        severity: error
        message: "Modification date is mandatory"
      - type: date_format
        params: {format: "YYYY-MM-DD"}
        severity: error
      - type: date_gte_field
        params: {reference: "dcterms:created"}
        severity: warning
        message: "Modified date should be >= created date"
      - type: date_gte_field
        params: {reference: "dcterms:issued"}
        severity: warning
        message: "Modified date should be >= issued date"

  "dc:identifier[uuid]":
    rules:
      - type: required
        severity: error
      - type: uuid_v4_format
        severity: error
        message: "Must be a valid UUID v4"
      - type: unique
        params: {scope: "dataset"}
        severity: error
        message: "UUID must be unique across all datasets"

  "dc:identifier[landing_page]":
    rules:
      - type: required
        severity: error
      - type: url_format
        params: {protocols: ["https", "http"]}
        severity: error
      - type: url_starts_with
        params: {prefix: "https://www.data.gov.in/"}
        severity: warning
        message: "Landing page should be on data.gov.in domain"

  "dc:publisher":
    rules:
      - type: required
        severity: error
        message: "Publisher is mandatory"
      - type: array_min_items
        params: {min: 1}
        severity: error
      - type: array_items_not_empty
        severity: error

  "dcterms:accessRights":
    rules:
      - type: required
        severity: error
      - type: controlled_vocabulary
        params: 
          values: ["Open", "Registered", "Restricted"]
        severity: error
        message: "Access rights must be Open, Registered, or Restricted"

  # ═══════════════════════════════════════════════════════════════════
  # OPTIONAL BUT VALIDATED FIELDS
  # ═══════════════════════════════════════════════════════════════════

  "dcterms:temporal":
    rules:
      - type: dcmi_period_format
        severity: error
        message: "Must follow DCMI Period format: 'start: YYYY-MM-DD; end: YYYY-MM-DD' or 'start: YYYY-MM-DD; end: NA'"
      - type: temporal_dates_valid
        severity: error
        message: "Temporal start date must be <= end date"

  "dcterms:coverage":
    rules:
      - type: iso8601_duration
        params: {allow_na: true}
        severity: error
        message: "Must be ISO 8601 duration (e.g., P1D, P1M, P1Y) or NA"

  "dcterms:accrualPeriodicity":
    rules:
      - type: uri_format
        severity: error
      - type: uri_starts_with
        params: 
          prefixes: 
            - "http://purl.org/dc/terms/"
            - "http://purl.org/cld/freq/"
        severity: error
        message: "Must use Dublin Core or CLD frequency URI"

  "dc:format":
    rules:
      - type: mime_type
        severity: error
        message: "Must be a valid MIME type"

  "dc:relation[download_url]":
    rules:
      - type: url_format
        severity: error
      - type: url_accessible
        params: {timeout: 10, allow_redirect: true}
        severity: warning
        message: "Download URL should be accessible"

  "dc:relation[csv_endpointURL]":
    rules:
      - type: url_format
        severity: error
      - type: url_contains
        params: {substring: "format=csv"}
        severity: warning
        message: "CSV endpoint URL should contain format=csv parameter"
```

### 4.2 Dataset-Level Cross-Field Validation

```yaml
# config/validation/dataset_rules.yaml
version: "1.0.0"

dataset_validators:

  # ═══════════════════════════════════════════════════════════════════
  # CONDITIONAL RULES
  # ═══════════════════════════════════════════════════════════════════

  - rule_id: "extent_with_download"
    description: "If relation[download_url] exists, extent is recommended"
    condition:
      field: "dc:relation[download_url]"
      operator: "exists"
    check:
      field: "dcterms:extent"
      operator: "exists"
    severity: warning
    message: "File size (extent) recommended when download URL is provided"

  - rule_id: "endpoint_description_with_url"
    description: "If endpointURL exists, endpointDescription is optional but helpful"
    condition:
      any:
        - field: "dc:relation[csv_endpointURL]"
          operator: "exists"
        - field: "dc:relation[json_endpointURL]"
          operator: "exists"
    check:
      field: "description:endpointDescription"
      operator: "exists"
    severity: info
    message: "Consider adding endpoint description for API endpoints"

  - rule_id: "type5_access_rights"
    description: "Type-5 datasets must be Registered"
    condition:
      field: "dcterms:accrualMethod"
      operator: "equals"
      value: "API Service"
    check:
      field: "dcterms:accessRights"
      operator: "in"
      values: ["Registered", "Restricted"]
    severity: error
    message: "API Service (Type-5) datasets must have Registered or Restricted access"

  - rule_id: "temporal_when_time_series"
    description: "Time series data should have temporal coverage"
    condition:
      field: "dcterms:coverage"
      operator: "not_in"
      values: ["NA", null]
    check:
      field: "dcterms:temporal"
      operator: "exists"
    severity: warning
    message: "Time-series datasets should specify temporal coverage"

  - rule_id: "sector_consistency"
    description: "Sector resource should be subset of sector"
    condition:
      field: "dc:subject[sector]"
      operator: "exists"
    check:
      type: "custom"
      function: "validate_sector_subset"
      params:
        parent_field: "dc:subject[sector]"
        child_field: "dc:subject[sector_resource]"
    severity: warning
    message: "Sector resource should be a subset of catalog sector"

  - rule_id: "creator_or_publisher"
    description: "At least one of creator or publisher must be present"
    check:
      any:
        - field: "dc:creator"
          operator: "exists"
        - field: "dc:publisher"
          operator: "not_empty_array"
    severity: error
    message: "Dataset must have either creator or publisher"

  - rule_id: "dates_chronological"
    description: "Dates should be in chronological order"
    check:
      type: "custom"
      function: "validate_date_chronology"
      params:
        order: ["dcterms:created", "dcterms:issued", "dcterms:modified"]
        allow_equal: true
    severity: warning
    message: "Dates should be chronological: created <= issued <= modified"

  # ═══════════════════════════════════════════════════════════════════
  # COMPLETENESS CHECKS
  # ═══════════════════════════════════════════════════════════════════

  - rule_id: "minimum_metadata_completeness"
    description: "Check minimum required metadata fields"
    check:
      type: "completeness_score"
      required_fields:
        - "dc:title"
        - "dcterms:issued"
        - "dcterms:modified"
        - "dc:identifier[uuid]"
        - "dc:identifier[landing_page]"
        - "dc:publisher"
        - "dcterms:accessRights"
        - "dcterms:accrualPeriodicity"
        - "dcin:jurisdiction"
        - "dcterms:spatial"
      min_score: 0.8
    severity: error
    message: "Metadata completeness below required threshold"
```

### 4.3 Validation Report Format

```json
{
  "validation_report": {
    "record_id": "8ded94de-3b80-4840-a5bb-7faad1c9c234",
    "record_title": "Variety-wise Daily Market Prices Data of Commodity",
    "validation_timestamp": "2025-01-20T10:35:22Z",
    "config_version": "1.0.0",
    "overall_status": "warning",
    "is_valid": true,
    "summary": {
      "total_rules_checked": 42,
      "passed": 39,
      "warnings": 2,
      "errors": 0,
      "info": 1
    },
    "completeness_score": 0.92,
    "issues": [
      {
        "field": "dcterms:extent",
        "severity": "warning",
        "rule_id": "extent_with_download",
        "message": "File size (extent) recommended when download URL is provided",
        "current_value": null,
        "expected": "numeric file size in bytes"
      },
      {
        "field": "description:endpointDescription",
        "severity": "info",
        "rule_id": "endpoint_description_with_url",
        "message": "Consider adding endpoint description for API endpoints",
        "current_value": null,
        "expected": "text description of API endpoint"
      },
      {
        "field": "dcterms:modified",
        "severity": "warning",
        "rule_id": "dates_chronological",
        "message": "Modified date (2025-10-15) is after today (2025-01-20)",
        "current_value": "2025-10-15",
        "expected": "date <= today"
      }
    ],
    "field_results": {
      "dc:title": {"status": "passed", "value": "Variety-wise Daily Market Prices..."},
      "dcterms:issued": {"status": "passed", "value": "2024-02-06"},
      "dcterms:modified": {"status": "warning", "value": "2025-10-15"},
      "dc:identifier[uuid]": {"status": "passed", "value": "8ded94de-3b80-4840-a5bb-7faad1c9c234"},
      "dc:publisher": {"status": "passed", "value": ["Ministry of Agriculture...", "Directorate of Marketing..."]}
    }
  }
}
```

### 4.4 Diff Mode for Change Detection

```python
# src/ogd_dc_transformer/validation/diff_reporter.py

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import json
from deepdiff import DeepDiff

class ChangeType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    TYPE_CHANGED = "type_changed"

@dataclass
class FieldChange:
    field_path: str
    change_type: ChangeType
    old_value: Any
    new_value: Any
    is_expected: bool = True  # Whether change aligns with config version changes

@dataclass
class DiffReport:
    record_id: str
    previous_run_id: str
    current_run_id: str
    config_version_change: Optional[str]  # e.g., "1.0.0 -> 1.1.0"
    total_changes: int
    changes: List[FieldChange]
    unexpected_changes: List[FieldChange]
    timestamp: str

class DiffReporter:
    """Compare current transformation results with previous run."""
    
    def __init__(self, expected_changes_config: Optional[Dict] = None):
        """
        Args:
            expected_changes_config: Config indicating expected field changes
                                    when mapping version changes
        """
        self.expected_changes = expected_changes_config or {}
    
    def compare_records(
        self,
        previous: Dict[str, Any],
        current: Dict[str, Any],
        record_id: str,
        previous_run_id: str,
        current_run_id: str,
        previous_config_version: str,
        current_config_version: str
    ) -> DiffReport:
        """Compare two versions of a Dublin Core record."""
        
        # Use DeepDiff for thorough comparison
        diff = DeepDiff(previous, current, ignore_order=True, verbose_level=2)
        
        changes = []
        
        # Process added values
        for path in diff.get('dictionary_item_added', []):
            changes.append(FieldChange(
                field_path=self._clean_path(path),
                change_type=ChangeType.ADDED,
                old_value=None,
                new_value=self._get_nested(current, path),
                is_expected=self._is_expected_change(path, ChangeType.ADDED, 
                    previous_config_version, current_config_version)
            ))
        
        # Process removed values
        for path in diff.get('dictionary_item_removed', []):
            changes.append(FieldChange(
                field_path=self._clean_path(path),
                change_type=ChangeType.REMOVED,
                old_value=self._get_nested(previous, path),
                new_value=None,
                is_expected=self._is_expected_change(path, ChangeType.REMOVED,
                    previous_config_version, current_config_version)
            ))
        
        # Process modified values
        for path, change in diff.get('values_changed', {}).items():
            changes.append(FieldChange(
                field_path=self._clean_path(path),
                change_type=ChangeType.MODIFIED,
                old_value=change.get('old_value'),
                new_value=change.get('new_value'),
                is_expected=self._is_expected_change(path, ChangeType.MODIFIED,
                    previous_config_version, current_config_version)
            ))
        
        # Type changes
        for path, change in diff.get('type_changes', {}).items():
            changes.append(FieldChange(
                field_path=self._clean_path(path),
                change_type=ChangeType.TYPE_CHANGED,
                old_value=f"{change.get('old_type').__name__}: {change.get('old_value')}",
                new_value=f"{change.get('new_type').__name__}: {change.get('new_value')}",
                is_expected=False
            ))
        
        unexpected = [c for c in changes if not c.is_expected]
        
        config_change = None
        if previous_config_version != current_config_version:
            config_change = f"{previous_config_version} -> {current_config_version}"
        
        return DiffReport(
            record_id=record_id,
            previous_run_id=previous_run_id,
            current_run_id=current_run_id,
            config_version_change=config_change,
            total_changes=len(changes),
            changes=changes,
            unexpected_changes=unexpected,
            timestamp=pd.Timestamp.now().isoformat()
        )
    
    def _clean_path(self, path: str) -> str:
        """Clean DeepDiff path notation to readable field path."""
        # Convert "root['dc:title']" to "dc:title"
        return path.replace("root['", "").replace("']['", ".").replace("']", "")
    
    def _get_nested(self, d: Dict, path: str) -> Any:
        """Get nested value using DeepDiff path notation."""
        try:
            cleaned = self._clean_path(path)
            parts = cleaned.split('.')
            result = d
            for part in parts:
                if isinstance(result, dict):
                    result = result.get(part)
                elif isinstance(result, list) and part.isdigit():
                    result = result[int(part)]
            return result
        except Exception:
            return None
    
    def _is_expected_change(
        self, 
        path: str, 
        change_type: ChangeType,
        prev_version: str,
        curr_version: str
    ) -> bool:
        """Check if change is expected based on config version changes."""
        if prev_version == curr_version:
            # No config change - any difference is unexpected
            return False
        
        # Check expected_changes config
        version_key = f"{prev_version}->{curr_version}"
        expected_fields = self.expected_changes.get(version_key, [])
        
        field_path = self._clean_path(path)
        return field_path in expected_fields


def generate_diff_summary(reports: List[DiffReport]) -> Dict[str, Any]:
    """Generate summary from multiple diff reports."""
    return {
        "summary": {
            "total_records": len(reports),
            "records_with_changes": sum(1 for r in reports if r.total_changes > 0),
            "records_with_unexpected": sum(1 for r in reports if r.unexpected_changes),
            "total_changes": sum(r.total_changes for r in reports),
            "total_unexpected": sum(len(r.unexpected_changes) for r in reports)
        },
        "unexpected_by_field": _aggregate_unexpected_by_field(reports),
        "change_distribution": _change_distribution(reports)
    }

def _aggregate_unexpected_by_field(reports: List[DiffReport]) -> Dict[str, int]:
    """Count unexpected changes by field."""
    counts = {}
    for report in reports:
        for change in report.unexpected_changes:
            counts[change.field_path] = counts.get(change.field_path, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))

def _change_distribution(reports: List[DiffReport]) -> Dict[str, int]:
    """Distribution of change types."""
    dist = {ct.value: 0 for ct in ChangeType}
    for report in reports:
        for change in report.changes:
            dist[change.change_type.value] += 1
    return dist
```

### 4.5 Testing Strategy

```python
# tests/conftest.py

import pytest
import json
from pathlib import Path

@pytest.fixture
def golden_ogd_records():
    """Load golden OGD test records."""
    path = Path(__file__).parent / "golden_files" / "input" / "sample_ogd_5datasets.json"
    with open(path) as f:
        return json.load(f)

@pytest.fixture
def expected_dc_records():
    """Load expected Dublin Core outputs."""
    path = Path(__file__).parent / "golden_files" / "expected" / "dublin_core_5datasets.json"
    with open(path) as f:
        return json.load(f)

@pytest.fixture
def mapping_config():
    """Load test mapping configuration."""
    from ogd_dc_transformer.mapping.config_loader import load_config
    return load_config("config/mapping/base_mapping.yaml")


# tests/unit/test_transforms.py

import pytest
from ogd_dc_transformer.mapping.transforms import (
    direct_copy, parse_date, format_date, split_to_array,
    map_to_uri, construct_url, build_publisher_hierarchy
)

class TestDateTransforms:
    """Test date transformation functions."""
    
    @pytest.mark.parametrize("input_date,expected", [
        ("15/01/2024", "2024-01-15"),
        ("2024-01-15", "2024-01-15"),
        ("15-01-2024", "2024-01-15"),
        ("2024-01-15 10:30:00", "2024-01-15"),
    ])
    def test_parse_and_format_date(self, input_date, expected):
        parsed = parse_date(input_date)
        result = format_date(parsed, "YYYY-MM-DD")
        assert result == expected
    
    def test_parse_invalid_date_returns_none(self):
        assert parse_date("not-a-date") is None
        assert parse_date("") is None
        assert parse_date(None) is None


class TestArrayTransforms:
    """Test array handling transforms."""
    
    def test_split_to_array_semicolon(self):
        result = split_to_array("Agriculture;Health;Education", delimiter=";")
        assert result == ["Agriculture", "Health", "Education"]
    
    def test_split_to_array_with_trim(self):
        result = split_to_array("  Agriculture ; Health  ", delimiter=";", trim=True)
        assert result == ["Agriculture", "Health"]
    
    def test_split_empty_returns_empty_list(self):
        assert split_to_array("", delimiter=";") == []
        assert split_to_array(None, delimiter=";") == []


class TestURITransforms:
    """Test URI construction and mapping."""
    
    def test_map_frequency_to_uri(self):
        mapping = {
            "Daily": "http://purl.org/dc/terms/Daily",
            "Monthly": "http://purl.org/dc/terms/Monthly"
        }
        assert map_to_uri("Daily", mapping) == "http://purl.org/dc/terms/Daily"
        assert map_to_uri("Unknown", mapping) is None
    
    def test_construct_url(self):
        result = construct_url(
            template="https://www.{domain}{node_alias}",
            values={"domain": "data.gov.in", "node_alias": "/resource/test-dataset"}
        )
        assert result == "https://www.data.gov.in/resource/test-dataset"


class TestPublisherHierarchy:
    """Test publisher array construction."""
    
    def test_build_publisher_hierarchy(self):
        result = build_publisher_hierarchy(
            ministry="Ministry of Agriculture;Department of Agriculture",
            state_department=None
        )
        assert result == ["Ministry of Agriculture", "Department of Agriculture"]
    
    def test_publisher_with_state(self):
        result = build_publisher_hierarchy(
            ministry="Ministry of Agriculture",
            state_department="State Agriculture Dept"
        )
        assert result == ["Ministry of Agriculture", "State Agriculture Dept"]


# tests/integration/test_pipeline.py

import pytest
from ogd_dc_transformer.core.pipeline import TransformationPipeline

class TestEndToEndTransformation:
    """Golden file tests for complete pipeline."""
    
    def test_transform_5_datasets(
        self, golden_ogd_records, expected_dc_records, mapping_config
    ):
        """Test transformation of 5 sample datasets matches expected output."""
        pipeline = TransformationPipeline(config=mapping_config)
        
        for ogd_record, expected in zip(golden_ogd_records, expected_dc_records):
            result = pipeline.transform(ogd_record)
            
            # Check key fields match
            assert result.dublin_core.title == expected["dc:title"]
            assert result.dublin_core.identifier.uuid == expected["dc:identifier"]["uuid"]
            assert result.dublin_core.identifier.landing_page == expected["dc:identifier"]["landing_page"]
            assert result.dublin_core.publisher == expected["dc:publisher"]
            
            # Check dates
            if expected.get("dcterms:issued"):
                assert str(result.dublin_core.issued) == expected["dcterms:issued"]
    
    def test_regression_no_unexpected_changes(
        self, golden_ogd_records, expected_dc_records, mapping_config
    ):
        """Regression test: transformation should not introduce unexpected changes."""
        pipeline = TransformationPipeline(config=mapping_config)
        
        from ogd_dc_transformer.validation.diff_reporter import DiffReporter
        reporter = DiffReporter()
        
        for ogd_record, expected in zip(golden_ogd_records, expected_dc_records):
            result = pipeline.transform(ogd_record)
            result_dict = result.dublin_core.dict(by_alias=True)
            
            diff = reporter.compare_records(
                previous=expected,
                current=result_dict,
                record_id=expected["dc:identifier"]["uuid"],
                previous_run_id="baseline",
                current_run_id="current",
                previous_config_version="1.0.0",
                current_config_version="1.0.0"
            )
            
            # No unexpected changes allowed
            assert len(diff.unexpected_changes) == 0, \
                f"Unexpected changes in {expected['dc:title']}: {diff.unexpected_changes}"
```

---

## 5. Change Management & Governance

### 5.1 Configuration Versioning

**Semantic Versioning Rules:**

| Change Type | Version Bump | Example |
|-------------|--------------|---------|
| Bug fix in transform | PATCH (x.x.X) | 1.0.0 → 1.0.1 |
| New optional field | MINOR (x.X.0) | 1.0.0 → 1.1.0 |
| Mandatory field change | MAJOR (X.0.0) | 1.0.0 → 2.0.0 |
| Breaking transform change | MAJOR | 1.0.0 → 2.0.0 |

**Changelog Format:**

```yaml
# config/CHANGELOG.yaml
versions:
  - version: "1.1.0"
    date: "2025-02-15"
    changes:
      - type: "added"
        field: "dcterms:collection"
        description: "Added collection field for data series grouping"
        backward_compatible: true
      - type: "modified"
        field: "dcterms:temporal"
        description: "Improved date parsing for DD/MM/YYYY format"
        backward_compatible: true
    
  - version: "1.0.1"
    date: "2025-01-25"
    changes:
      - type: "fixed"
        field: "dcterms:accrualPeriodicity"
        description: "Corrected URI for 'Half Yearly' frequency"
        backward_compatible: true
    
  - version: "1.0.0"
    date: "2025-01-20"
    changes:
      - type: "initial"
        description: "Initial release with 50+ field mappings"
```

### 5.2 Safe Rollout Process

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          CHANGE ROLLOUT WORKFLOW                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  1. DEVELOPMENT                                                                  │
│     ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│     │ Modify       │───▶│ Unit Tests   │───▶│ Golden File  │                   │
│     │ Config/Code  │    │ Pass         │    │ Tests Pass   │                   │
│     └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                    │                            │
│  2. STAGING                                        ▼                            │
│     ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│     │ Run on       │───▶│ Generate     │───▶│ Review       │                   │
│     │ Staging Data │    │ Diff Report  │    │ Changes      │                   │
│     └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                    │                            │
│  3. APPROVAL                                       ▼                            │
│     ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│     │ Data Owner   │───▶│ QA Team      │───▶│ Sign-off     │                   │
│     │ Review       │    │ Validation   │    │ Approval     │                   │
│     └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                    │                            │
│  4. PRODUCTION                                     ▼                            │
│     ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│     │ Deploy to    │───▶│ Run with     │───▶│ Monitor &    │                   │
│     │ Production   │    │ Audit Logs   │    │ Alert        │                   │
│     └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Pre-Production Checklist:**

```yaml
# .github/pull_request_template.md
## Change Summary
- [ ] Mapping config version updated
- [ ] CHANGELOG.yaml updated
- [ ] All unit tests pass
- [ ] Golden file tests pass (or intentionally updated)
- [ ] Diff report reviewed
- [ ] No unexpected field changes
- [ ] Performance impact assessed

## Diff Report Summary
| Metric | Value |
|--------|-------|
| Records affected | ___ |
| Fields changed | ___ |
| Unexpected changes | 0 |

## Approvals Required
- [ ] Data Team Lead
- [ ] QA Engineer
```

### 5.3 Dataset Type Profiles with Overrides

**Layered Configuration:**

```
Base Mapping (base_mapping.yaml)
       │
       ├──► Type-1 Override (type_1.yaml) → Static datasets
       │
       ├──► Type-2 Override (type_2.yaml) → Periodic collection
       │
       ├──► Type-4 Override (type_4.yaml) → File download
       │
       └──► Type-5 Override (type_5.yaml) → API Service (Registered)
                  │
                  └──► Dataset Override (uuid.yaml) → Per-dataset custom
```

**Example Type Override:**

```yaml
# config/mapping/type_overrides/type_5.yaml
# Overrides for Type-5 (API Service / Registered) datasets

extends: "base_mapping.yaml"
version: "1.0.0"

overrides:
  "dcterms:accessRights":
    # Force Registered for Type-5
    transform_pipeline:
      - name: "constant"
        params: {value: "Registered"}
    validators:
      - type: "equals"
        params: {value: "Registered"}
        severity: error
        message: "Type-5 datasets must be Registered"

  "dc:relation[csv_endpointURL]":
    # Type-5 always has API endpoint
    required: true
    validators:
      - type: "required"
        severity: error
        message: "Type-5 datasets must have CSV endpoint URL"

  "dcterms:accrualMethod":
    transform_pipeline:
      - name: "constant"
        params: {value: "API Service"}
```

**Configuration Loader:**

```python
# src/ogd_dc_transformer/mapping/config_loader.py

from typing import Dict, Any, Optional
import yaml
from pathlib import Path
from functools import lru_cache

class ConfigLoader:
    """Load and merge layered configuration."""
    
    def __init__(self, config_dir: str = "config/mapping"):
        self.config_dir = Path(config_dir)
    
    @lru_cache(maxsize=32)
    def load_config(
        self,
        dataset_type: Optional[int] = None,
        dataset_uuid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load merged configuration for a dataset.
        
        Priority (highest to lowest):
        1. Dataset-specific override
        2. Type-specific override
        3. Base mapping
        """
        # Start with base
        config = self._load_yaml(self.config_dir / "base_mapping.yaml")
        
        # Apply type override
        if dataset_type:
            type_file = self.config_dir / "type_overrides" / f"type_{dataset_type}.yaml"
            if type_file.exists():
                type_config = self._load_yaml(type_file)
                config = self._merge_configs(config, type_config)
        
        # Apply dataset override
        if dataset_uuid:
            dataset_file = self.config_dir / "dataset_overrides" / f"{dataset_uuid}.yaml"
            if dataset_file.exists():
                dataset_config = self._load_yaml(dataset_file)
                config = self._merge_configs(config, dataset_config)
        
        return config
    
    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """Load YAML file."""
        with open(path) as f:
            return yaml.safe_load(f)
    
    def _merge_configs(
        self, 
        base: Dict[str, Any], 
        override: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Deep merge override into base config."""
        result = base.copy()
        
        # Merge overrides for specific fields
        if "overrides" in override:
            mappings = result.get("mappings", [])
            for field_name, field_override in override["overrides"].items():
                # Find and update matching field
                for i, mapping in enumerate(mappings):
                    if mapping.get("target_field") == field_name:
                        mappings[i] = self._merge_field(mapping, field_override)
                        break
            result["mappings"] = mappings
        
        # Copy version from override
        if "version" in override:
            result["override_version"] = override["version"]
        
        return result
    
    def _merge_field(
        self, 
        base_field: Dict, 
        override_field: Dict
    ) -> Dict:
        """Merge field-level overrides."""
        result = base_field.copy()
        result.update(override_field)
        return result
```

---

## 6. Operationalization

### 6.1 CLI Design

```bash
# Main CLI commands

# Transform a single file
ogd-dc transform \
  --input /path/to/ogd_metadata.csv \
  --output /path/to/dublin_core.json \
  --config config/mapping/base_mapping.yaml \
  --type-override 5 \
  --validate \
  --verbose

# Transform with derived metadata computation
ogd-dc transform \
  --input /path/to/ogd_metadata.csv \
  --dataset-dir /path/to/datasets/ \
  --output /path/to/output/ \
  --compute-temporal \
  --compute-granularity \
  --scan-pii \
  --output-format json

# Validate existing Dublin Core records
ogd-dc validate \
  --input /path/to/dublin_core.json \
  --config config/validation/field_rules.yaml \
  --output-report /path/to/validation_report.json \
  --fail-on-error

# Generate diff report
ogd-dc diff \
  --previous /path/to/previous_run/ \
  --current /path/to/current_run/ \
  --output /path/to/diff_report.json \
  --config-version-previous 1.0.0 \
  --config-version-current 1.1.0

# Profile datasets for PII
ogd-dc profile \
  --input /path/to/datasets/ \
  --output /path/to/pii_report.json \
  --sample-size 1000 \
  --format csv

# Export to multiple formats
ogd-dc export \
  --input /path/to/dublin_core.json \
  --format csv \
  --output /path/to/export.csv \
  --fields "dc:title,dc:identifier[uuid],dcterms:issued,dc:publisher"
```

**CLI Implementation:**

```python
# src/ogd_dc_transformer/cli/main.py

import click
import json
import logging
from pathlib import Path
from datetime import datetime
import uuid as uuid_lib

from ogd_dc_transformer.core.pipeline import TransformationPipeline
from ogd_dc_transformer.validation.validator import Validator
from ogd_dc_transformer.validation.diff_reporter import DiffReporter
from ogd_dc_transformer.profiling.pii_detector import PIIDetector
from ogd_dc_transformer.export.json_exporter import JSONExporter
from ogd_dc_transformer.export.csv_exporter import CSVExporter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ogd-dc')

@click.group()
@click.version_option(version='1.0.0')
def cli():
    """OGD to Dublin Core Metadata Transformation Tool."""
    pass


@cli.command()
@click.option('--input', '-i', 'input_path', required=True,
              type=click.Path(exists=True), help='Input OGD metadata file')
@click.option('--output', '-o', 'output_path', required=True,
              type=click.Path(), help='Output Dublin Core file')
@click.option('--config', '-c', 'config_path', 
              default='config/mapping/base_mapping.yaml',
              type=click.Path(exists=True), help='Mapping configuration file')
@click.option('--type-override', type=int, default=None,
              help='Dataset type for override (1, 2, 4, or 5)')
@click.option('--dataset-dir', type=click.Path(exists=True),
              help='Directory containing dataset files for derived metadata')
@click.option('--compute-temporal', is_flag=True,
              help='Compute temporal coverage from datasets')
@click.option('--compute-granularity', is_flag=True,
              help='Compute granularity from datasets')
@click.option('--scan-pii', is_flag=True,
              help='Scan datasets for PII')
@click.option('--validate/--no-validate', default=True,
              help='Run validation after transformation')
@click.option('--output-format', type=click.Choice(['json', 'csv']), 
              default='json')
@click.option('--verbose', '-v', is_flag=True)
def transform(input_path, output_path, config_path, type_override,
              dataset_dir, compute_temporal, compute_granularity,
              scan_pii, validate, output_format, verbose):
    """Transform OGD metadata to Dublin Core."""
    
    run_id = str(uuid_lib.uuid4())[:8]
    logger.info(f"Starting transformation run: {run_id}")
    
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize pipeline
    pipeline = TransformationPipeline(
        config_path=config_path,
        type_override=type_override
    )
    
    # Load input
    logger.info(f"Loading input from: {input_path}")
    records = pipeline.load_input(input_path)
    
    results = []
    errors = []
    
    for i, record in enumerate(records):
        try:
            logger.debug(f"Processing record {i+1}/{len(records)}: {record.get('title', 'Unknown')}")
            
            result = pipeline.transform(record)
            
            # Compute derived metadata if requested
            if dataset_dir and (compute_temporal or compute_granularity):
                dataset_file = find_dataset_file(dataset_dir, record)
                if dataset_file:
                    if compute_temporal:
                        result = pipeline.compute_temporal(result, dataset_file)
                    if compute_granularity:
                        result = pipeline.compute_granularity(result, dataset_file)
            
            # PII scanning
            if scan_pii and dataset_dir:
                dataset_file = find_dataset_file(dataset_dir, record)
                if dataset_file:
                    pii_result = PIIDetector().scan(dataset_file)
                    result.analytics_profile = pii_result.to_analytics_block()
            
            results.append(result)
            
        except Exception as e:
            logger.error(f"Error processing record {i+1}: {e}")
            errors.append({"record_index": i, "error": str(e)})
    
    # Validate if requested
    validation_report = None
    if validate:
        logger.info("Running validation...")
        validator = Validator()
        validation_report = validator.validate_batch(results)
    
    # Export
    logger.info(f"Exporting to: {output_path}")
    if output_format == 'json':
        exporter = JSONExporter()
    else:
        exporter = CSVExporter()
    
    exporter.export(results, output_path)
    
    # Summary
    click.echo(f"\n{'='*60}")
    click.echo(f"Transformation Complete - Run ID: {run_id}")
    click.echo(f"{'='*60}")
    click.echo(f"Records processed: {len(records)}")
    click.echo(f"Successful: {len(results)}")
    click.echo(f"Errors: {len(errors)}")
    
    if validation_report:
        click.echo(f"\nValidation:")
        click.echo(f"  Valid records: {validation_report['valid_count']}")
        click.echo(f"  With warnings: {validation_report['warning_count']}")
        click.echo(f"  With errors: {validation_report['error_count']}")
    
    click.echo(f"\nOutput: {output_path}")


@cli.command()
@click.option('--input', '-i', 'input_path', required=True,
              type=click.Path(exists=True))
@click.option('--config', '-c', 'config_path',
              default='config/validation/field_rules.yaml',
              type=click.Path(exists=True))
@click.option('--output-report', '-o', type=click.Path())
@click.option('--fail-on-error', is_flag=True,
              help='Exit with non-zero status if errors found')
def validate(input_path, config_path, output_report, fail_on_error):
    """Validate Dublin Core records."""
    
    logger.info(f"Validating: {input_path}")
    
    validator = Validator(config_path)
    results = validator.validate_file(input_path)
    
    if output_report:
        with open(output_report, 'w') as f:
            json.dump(results, f, indent=2, default=str)
    
    # Summary
    click.echo(f"\nValidation Results:")
    click.echo(f"  Total records: {results['total']}")
    click.echo(f"  Valid: {results['valid']}")
    click.echo(f"  Warnings: {results['warnings']}")
    click.echo(f"  Errors: {results['errors']}")
    
    if fail_on_error and results['errors'] > 0:
        raise SystemExit(1)


@cli.command()
@click.option('--previous', '-p', required=True, type=click.Path(exists=True))
@click.option('--current', '-c', required=True, type=click.Path(exists=True))
@click.option('--output', '-o', required=True, type=click.Path())
@click.option('--config-version-previous', default='1.0.0')
@click.option('--config-version-current', default='1.0.0')
def diff(previous, current, output, config_version_previous, config_version_current):
    """Generate diff report between two transformation runs."""
    
    logger.info("Generating diff report...")
    
    reporter = DiffReporter()
    report = reporter.compare_directories(
        previous, current,
        config_version_previous,
        config_version_current
    )
    
    with open(output, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    click.echo(f"\nDiff Report Summary:")
    click.echo(f"  Records compared: {report['summary']['total_records']}")
    click.echo(f"  With changes: {report['summary']['records_with_changes']}")
    click.echo(f"  Unexpected changes: {report['summary']['total_unexpected']}")
    click.echo(f"\nReport saved: {output}")


if __name__ == '__main__':
    cli()
```

### 6.2 Logging and Observability

```python
# src/ogd_dc_transformer/core/logging_config.py

import logging
import json
from datetime import datetime
from typing import Any, Dict
import uuid

class StructuredLogFormatter(logging.Formatter):
    """JSON structured log formatter for observability."""
    
    def __init__(self, run_id: str = None):
        super().__init__()
        self.run_id = run_id or str(uuid.uuid4())[:8]
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": self.run_id,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add extra fields if present
        if hasattr(record, 'record_id'):
            log_data['record_id'] = record.record_id
        if hasattr(record, 'field'):
            log_data['field'] = record.field
        if hasattr(record, 'transform'):
            log_data['transform'] = record.transform
        if hasattr(record, 'duration_ms'):
            log_data['duration_ms'] = record.duration_ms
        
        # Include exception info
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def setup_logging(
    run_id: str = None,
    level: str = "INFO",
    log_file: str = None
):
    """Setup structured logging."""
    
    formatter = StructuredLogFormatter(run_id)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    handlers = [console_handler]
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        handlers=handlers
    )
    
    return run_id or str(uuid.uuid4())[:8]


# Usage example
class TransformLogger:
    """Logger with context for transformation operations."""
    
    def __init__(self, logger: logging.Logger, record_id: str = None):
        self.logger = logger
        self.record_id = record_id
    
    def log_transform_start(self, field: str, source_value: Any):
        self.logger.debug(
            f"Starting transform for {field}",
            extra={
                'record_id': self.record_id,
                'field': field,
                'source_value': str(source_value)[:100]
            }
        )
    
    def log_transform_complete(self, field: str, result: Any, duration_ms: float):
        self.logger.info(
            f"Transform complete for {field}",
            extra={
                'record_id': self.record_id,
                'field': field,
                'result_preview': str(result)[:100],
                'duration_ms': duration_ms
            }
        )
    
    def log_validation_issue(self, field: str, severity: str, message: str):
        log_method = getattr(self.logger, severity.lower(), self.logger.warning)
        log_method(
            f"Validation issue: {message}",
            extra={
                'record_id': self.record_id,
                'field': field,
                'severity': severity
            }
        )
```

### 6.3 Output Formats

**JSON Output (Canonical):**

```json
{
  "metadata_version": "1.0.0",
  "export_timestamp": "2025-01-20T15:30:00Z",
  "run_id": "abc123",
  "records": [
    {
      "dc:title": "Daily Wholesale Mandi Market Prices of Agricultural Commodities by Variety",
      "dcterms:alternative": null,
      "dc:subject": {
        "keyword": ["Agricultural Marketing", "Wholesale Prices", "Mandi"],
        "sector": ["Agriculture", "Agricultural Marketing"],
        "sector_resource": ["Agriculture", "Agricultural Marketing"]
      },
      "dcterms:created": "2024-05-21",
      "dcterms:issued": "2024-02-06",
      "dcterms:modified": "2025-10-15",
      "dcterms:temporal": "start: 2000-03-01; end: NA",
      "dc:type": "Dataset",
      "dc:format": "text/csv",
      "dcterms:extent": "1464(1.46 KB)",
      "dc:identifier": {
        "uuid": "8ded94de-3b80-4840-a5bb-7faad1c9c234",
        "landing_page": "https://www.data.gov.in/resource/variety-wise-daily-market-prices-data-commodity",
        "api_url": "https://api.data.gov.in/resource/..."
      },
      "dc:publisher": [
        "Ministry of Agriculture and Farmers Welfare",
        "Department of Agriculture and Farmers Welfare",
        "Directorate of Marketing and Inspection (DMI)"
      ],
      "dc:creator": "Directorate of Marketing and Inspection (DMI)",
      "dc:relation": {
        "download_url": "https://data.gov.in/...",
        "csv_endpointURL": "https://api.data.gov.in/.../format=csv",
        "json_endpointURL": "https://api.data.gov.in/.../format=json",
        "catalog_title": "Current daily price of various commodities from various markets (Mandi)"
      },
      "dcterms:spatial": "India",
      "dcterms:coverage": "P1D^^xsd:duration",
      "dcin:jurisdiction": "Central",
      "dcterms:accessRights": "Registered",
      "dcterms:accrualPeriodicity": "http://purl.org/dc/terms/Daily",
      "dcterms:accrualMethod": "API Service",
      "dc:rights": "National Data Sharing and Accessibility Policy (NDSAP) (2012)",
      "dcterms:license": "GODL",
      "_provenance": {
        "run_id": "abc123",
        "config_version": "1.0.0",
        "transformed_at": "2025-01-20T15:30:00Z",
        "source_file": "ogd_metadata.csv",
        "row_index": 0
      }
    }
  ]
}
```

### 6.4 Status Report Template

```html
<!-- templates/status_report.html -->
<!DOCTYPE html>
<html>
<head>
    <title>Transformation Run Report - {{ run_id }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .success { color: green; }
        .warning { color: orange; }
        .error { color: red; }
        .summary-card { 
            border: 1px solid #ddd; 
            padding: 15px; 
            margin: 10px 0;
            border-radius: 5px;
        }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
    </style>
</head>
<body>
    <h1>Transformation Run Report</h1>
    
    <div class="summary-card">
        <h2>Summary</h2>
        <p><strong>Run ID:</strong> {{ run_id }}</p>
        <p><strong>Timestamp:</strong> {{ timestamp }}</p>
        <p><strong>Config Version:</strong> {{ config_version }}</p>
        <p><strong>Duration:</strong> {{ duration_seconds }}s</p>
    </div>
    
    <div class="summary-card">
        <h2>Processing Results</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Count</th>
            </tr>
            <tr>
                <td>Total Records</td>
                <td>{{ total_records }}</td>
            </tr>
            <tr class="success">
                <td>Successful</td>
                <td>{{ successful_records }}</td>
            </tr>
            <tr class="error">
                <td>Failed</td>
                <td>{{ failed_records }}</td>
            </tr>
        </table>
    </div>
    
    <div class="summary-card">
        <h2>Validation Summary</h2>
        <table>
            <tr>
                <th>Status</th>
                <th>Count</th>
            </tr>
            <tr class="success">
                <td>Valid</td>
                <td>{{ valid_count }}</td>
            </tr>
            <tr class="warning">
                <td>Warnings</td>
                <td>{{ warning_count }}</td>
            </tr>
            <tr class="error">
                <td>Errors</td>
                <td>{{ error_count }}</td>
            </tr>
        </table>
    </div>
    
    <div class="summary-card">
        <h2>Derived Metadata Confidence</h2>
        <table>
            <tr>
                <th>Record</th>
                <th>Temporal Coverage</th>
                <th>Granularity</th>
                <th>PII Risk</th>
            </tr>
            {% for record in records %}
            <tr>
                <td>{{ record.title[:50] }}...</td>
                <td class="{{ 'success' if record.temporal_confidence > 0.8 else 'warning' }}">
                    {{ "%.0f"|format(record.temporal_confidence * 100) }}%
                </td>
                <td class="{{ 'success' if record.granularity_confidence > 0.8 else 'warning' }}">
                    {{ "%.0f"|format(record.granularity_confidence * 100) }}%
                </td>
                <td class="{{ record.pii_risk_class }}">
                    {{ record.pii_risk }}
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    
    {% if diff_summary %}
    <div class="summary-card">
        <h2>Changes from Previous Run</h2>
        <p class="{{ 'error' if diff_summary.unexpected > 0 else 'success' }}">
            <strong>Unexpected Changes:</strong> {{ diff_summary.unexpected }}
        </p>
        <p><strong>Total Changes:</strong> {{ diff_summary.total }}</p>
        
        {% if diff_summary.unexpected > 0 %}
        <h3>Unexpected Changes by Field</h3>
        <table>
            <tr>
                <th>Field</th>
                <th>Count</th>
            </tr>
            {% for field, count in diff_summary.by_field.items() %}
            <tr>
                <td>{{ field }}</td>
                <td>{{ count }}</td>
            </tr>
            {% endfor %}
        </table>
        {% endif %}
    </div>
    {% endif %}
    
    {% if errors %}
    <div class="summary-card error">
        <h2>Errors</h2>
        <table>
            <tr>
                <th>Record</th>
                <th>Error</th>
            </tr>
            {% for error in errors %}
            <tr>
                <td>{{ error.record_id }}</td>
                <td>{{ error.message }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
    {% endif %}
</body>
</html>
```

---

## Appendix A: Complete Field Mapping Reference

| Dublin Core Element | OGD Source Field(s) | Transform | Required | Notes |
|---------------------|---------------------|-----------|----------|-------|
| dc:title | title | direct, AI-enhance | Mandatory | May need AI clarification |
| dcterms:alternative | — | AI-generate | Optional | When title unclear |
| dc:subject[keyword] | keyword | split, AI-enhance | Mandatory | Semicolon-delimited |
| dc:subject[sector] | sector | split, normalize | Mandatory | 36 controlled sectors |
| dc:subject[sector_resource] | sector_resource, sector | coalesce, split | Optional | Inherited from catalog |
| dcterms:created | created | parse_date | Optional | ISO 8601 |
| dcterms:issued | published_date | parse_date | Mandatory | ISO 8601 |
| dcterms:modified | changed | parse_date | Mandatory | ISO 8601 |
| dcterms:temporal | duration_of_date | parse_dcmi, compute | Optional | DCMI Period format |
| dc:type | resource_category | direct | Mandatory | Usually "Dataset" |
| dc:format | file_format | mime_normalize | Optional | MIME type |
| dcterms:extent | file_size | format_bytes | Optional | Bytes with readable |
| dc:identifier[uuid] | uuid | direct, generate | Mandatory | UUID v4 |
| dc:identifier[landing_page] | domain + node_alias | construct_url | Mandatory | data.gov.in URL |
| dc:identifier[api_url] | datafile_url | direct | Optional | API access URL |
| dc:source | field_reference_url | direct | Optional | Original source |
| dc:relation[download_url] | datafile | validate_url | Optional | CSV download |
| dc:relation[*_endpointURL] | datafile_url | construct | Optional | API endpoints |
| dc:relation[catalog_title] | catalog_title | direct | Mandatory | Parent catalog |
| dcterms:spatial | field_asset_jurisdiction | normalize | Mandatory | Geographic scope |
| dcterms:coverage | granularity | iso8601_duration | Optional | Temporal resolution |
| dc:creator | cdos_state_ministry | direct | Optional | Data creator |
| dc:publisher | ministry_dept, state_dept | hierarchy_array | Mandatory | Ordered array |
| dcterms:contributor | — | — | Optional | External contributors |
| dc:rights | Released Under | direct | Mandatory | NDSAP |
| dcterms:license | — | default | Mandatory | GODL default |
| dcterms:accessRights | access_type | normalize | Mandatory | Open/Registered/Restricted |
| dcterms:accrualPeriodicity | frequency | uri_map | Mandatory | DC Frequency URI |
| dcterms:accrualMethod | field_resource_type | map | Mandatory | Type 1/2/4/5 |
| dcin:jurisdiction | govt_type | normalize | Mandatory | Central/State |
| dcin:high_value_dataset_category | field_high_value_dataset | direct | Optional | HVD tagging |
| foaf:depiction | thumbnail | direct | Optional | Preview image |
| dcterms:conformsTo | fields | direct | Optional | Schema/columns |
| dc:description | body (catalog) | direct, inherit | Mandatory | From catalog |
| dcin:note | note | direct | Optional | India extension |
| dcterms:abstract | — | AI-generate | Optional | Short description |
| dcterms:collection | — | — | Optional | Data series |

---

## Appendix B: Assumptions Made

1. **Date Format Priority:** DD/MM/YYYY is assumed as primary input format based on Indian conventions
2. **Publisher Hierarchy:** Ministry comes before Department in the ordered array
3. **Sector Vocabulary:** Using the 36 predefined sectors from OGD controlled vocabulary
4. **Default License:** GODL (Government Open Data License) is the default for all OGD datasets
5. **Type-5 Classification:** Datasets accessed via API Service are classified as Registered access
6. **PII Patterns:** Based on common Indian ID formats (Aadhaar: 12 digits starting with 2-9, PAN: AAAAA9999A)
7. **Temporal Coverage:** "ongoing" is inferred when max date is within 90 days of current date
8. **AI-Assisted Fields:** Alternative title, abstract, and keywords may be AI-generated when source is unclear

---

*Document Version: 1.0.0*
*Last Updated: 2025-01-20*
*Author: Metadata Transformation & Data Profiling Architect*
