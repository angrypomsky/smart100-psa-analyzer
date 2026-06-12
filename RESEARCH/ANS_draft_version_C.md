# From Thermal-Hydraulic Outputs to DET Structure: An Automated Post-Processing Framework for SMR PSA

**[Author Name]**, **[Co-Author Name]**  
Department of Nuclear Engineering, Kyung Hee University, Republic of Korea  
[email address]

---

## Abstract

Improvements in computing performance have accelerated thermal-hydraulic (TH) simulation throughput in nuclear probabilistic safety assessment (PSA), resulting in datasets too large for efficient manual interpretation. Manual review introduces analyst fatigue and human error as scenario counts grow. This paper presents a framework that automatically extracts key safety function variables from MARS-KS TH simulation outputs and organizes them into an interactive Excel dashboard representing a dynamic event tree (DET) structure. Rather than binary success/failure classification, safety system states are defined by the number of operating trains (0–4), and the corresponding peak cladding temperature (PCT) distribution is visualized interactively. A relative-comparison algorithm enables robust train-count classification under varying initial conditions. Demonstrated on a synthetic dataset of 1,000 scenarios spanning five accident categories, the framework establishes the first step of a pipeline from TH simulation data toward automated event tree generation in PSA software-compatible format.

---

## I. INTRODUCTION

Advances in computing performance have substantially reduced the cost of TH simulation, enabling PSA studies to process larger scenario sets than previously feasible [5]. As simulation throughput increases, the volume of output data requiring interpretation grows proportionally. Manual review of individual output files — currently the norm in PSA practice — scales poorly: as scenario counts reach into the hundreds, the time burden on analysts increases accordingly, and the probability of fatigue-induced error rises [5]. Ensuring consistent safety function judgments across large datasets therefore requires automated post-processing.

In Level 1 PSA, each TH simulation scenario must be translated into a set of safety function success or failure judgments to contribute to core damage frequency (CDF) quantification [1]. Key variables include reactor trip (RT) timing, safety system operating status, and peak cladding temperature (PCT) — the surrogate for core damage under the NRC 10 CFR 50.46 criterion of 1477 K [2]. Extracting these variables consistently and correctly across hundreds of scenarios is the precondition for any downstream PSA analysis.

Beyond extraction, a structural limitation of conventional PSA event trees constrains the depth of safety analysis possible. Standard event tree branches classify each safety function as either success or failure. For multi-train systems such as PRHRS, this binary representation discards information about partial system performance: a scenario with two active trains out of four is treated identically to one with zero active trains, if both fall below the success criterion. A dynamic event tree (DET) structure addresses this by retaining the discrete train count as a branching variable, exposing the sensitivity of PCT distribution to marginal changes in system availability.

This paper presents a framework that addresses both the extraction and the representation challenges. An automated pipeline processes MARS-KS TH outputs to extract safety function variables, which are then organized into an interactive Excel dashboard with DET-equivalent structure: analysts select a train count combination and immediately observe the corresponding PCT distribution. This constitutes the first step of a larger pipeline — from raw TH simulation output, through DET-structured visualization, toward automated event tree generation in PSA software-compatible format.

---

## II. METHODOLOGY

### II.A. Framework Architecture

The framework is implemented as a Python-based pipeline with a modular object-oriented design — a software structure in which common logic is defined once in a base class and reused across accident-specific modules without duplication. A base analyzer class provides common logic for all accident types, with accident-specific subclasses overriding only the parameter configurations.

### II.B. Variable Mapping (VarMapper)

MARS-KS output files contain simulation variables identified by name strings whose format varies across reactor designs. The VarMapper module parses the MARS-KS variable name file and maps output columns to functional roles (PRHRS heat exchanger outputs, cladding temperature, reactor power) using keyword matching. This approach allows the framework to be applied to different reactor designs by updating only the keyword dictionary, without modifying the core algorithm.

### II.C. Reactor Trip Detection

RT timing is detected by identifying the point at which reactor power (rktpow) decreases to 20% of its initial value. For the RT-based PCT window used in the core damage judgment, a stricter 10% threshold is applied to exclude post-trip power transients from the PCT extraction window. If the simulation data begins after RT has already occurred (pre-truncated output), the algorithm returns the earliest available time as a fallback — a default behavior that allows processing to continue without error.

### II.D. Relative-Comparison PRHRS Assessment Algorithm

The core algorithmic contribution of this work is the relative-comparison method for PRHRS train counting. Conventional methods apply a fixed absolute threshold to each PRHRS heat exchanger (HX) output to classify it as active or inactive. This approach fails when the overall thermal load of the simulation varies: in a low-power scenario, all four trains may appear inactive under a fixed threshold even when functioning normally.

The proposed algorithm classifies train *i* as active if:

$$Q_i^{\text{agg}} \geq Q_{\max}^{\text{agg}} \times R_{\text{threshold}}$$

where $Q_i^{\text{agg}}$ is the time-averaged heat output of train *i* over the designated assessment window, $Q_{\max}^{\text{agg}}$ is the maximum such value across all four trains, and $R_{\text{threshold}}$ is set to 0.10 (10%). This relative criterion scales automatically with the thermal conditions of each simulation scenario.

The aggregation window and minimum floor value are configured per accident type based on the physical behavior of each event, as summarized in Table I.

**TABLE I. PRHRS Algorithm Parameters by Accident Type**

| Parameter | LOFW | SBLOCA | GTRN | LSSB | SGTR |
|-----------|------|--------|------|------|------|
| Aggregation window | Full mean | Full mean | Full mean | Full mean | Last 30% |
| Wait time (s) | 100 | 100 | 100 | 100 | 100 |
| Floor (W) | 1×10⁵ | 1×10⁵ | 1×10⁵ | 1×10⁵ | 1×10⁵ |

For LSSB, a large initial thermal transient produces a brief period of high HX output across all trains; the last-30% window aggregation excludes this artifact and captures only the steady post-transient state. For SGTR, the heat output behavior stabilizes in the latter portion of the transient, similar to LSSB; accordingly, the last-30% averaging window is applied by the same rationale.

### II.E. PCT Extraction and Core Damage Judgment

PCT is extracted as the maximum cladding temperature value occurring after the RT time point identified using the 10% threshold. Values exceeding 10,000 K are excluded as non-physical artifacts. Core damage is classified as: *CD* if PCT ≥ 1477 K, and *OK* otherwise [2].

### II.F. Dashboard and DET Structure

Extracted variables (RT outcome, PRHRS train count per accident type, PCT, CD judgment) are loaded into an Excel dashboard. The dashboard presents PCT distribution filtered by safety system operating train count, allowing analysts to observe how the distribution shifts as the number of active trains changes. This structure is equivalent to a DET representation: rather than binary success/failure branching, each safety system state is defined by its discrete train count (0–4), and the PCT distribution for each state is directly visualized. This enables interactive sensitivity analysis of success criteria without rerunning simulations.

---

## III. DEMONSTRATION RESULTS

### III.A. Reference Dataset

A synthetic demonstration dataset of 1,000 scenarios was generated to test the framework under a range of conditions spanning all five accident types (200 scenarios each). The dataset was constructed with stratified sampling — a method that ensures each subgroup (e.g., each PRHRS train count level and RT outcome) is represented in proportion — to cover the full range of operating conditions. Physical consistency was enforced through four validation rules: (A) PCT-outcome consistency with the 1477 K threshold, (B) PRHRS monotonicity (more active trains → lower PCT), (C) ATWS penalty logic (Anticipated Transient Without Scram: RT failure → elevated PCT), and (D) feed-and-bleed activation constraints. All 1,000 scenarios satisfied all four rules with zero violations.

### III.B. Algorithm Performance

The RT detection algorithm and PRHRS train counting algorithm were verified against manual assessment for a subset of scenarios across all five accident types, achieving 100% agreement. The PCT distribution for the reference dataset spans 700–1400 K, consistent with the physical range expected for a passively cooled SMR under representative accident conditions.

**TABLE II. Validation Summary**

| Algorithm | Verification Method | Result |
|-----------|-------------------|--------|
| RT detection | Manual comparison, all 5 types | 100% match |
| PRHRS train count | Manual comparison, all 5 types | 100% match |
| PCT extraction | Range check (700–1400 K) | Physically consistent |
| Dataset integrity | 4-rule logical validation | 0 violations / 1000 scenarios |

### III.C. Dashboard Results

For each accident type, the dashboard displays PCT distribution segmented by PRHRS operating train count, enabling direct visual comparison across system states. Filtering by train count shifts the PCT distribution toward lower values as train count increases, confirming the physical monotonicity of the system response. Processing time for the 1,000-scenario dataset is under 30 seconds on standard hardware.

---

## IV. CONCLUSIONS

This paper presents a framework that converts raw TH simulation outputs into a DET-structured interactive dashboard — the first step of a pipeline from simulation data toward automated event tree generation for PSA. The relative-comparison-based PRHRS train counting algorithm provides robust classification under varying initial conditions, and the VarMapper module ensures applicability across reactor designs without code modification. By representing safety system states as discrete train counts rather than binary success/failure, the dashboard exposes the sensitivity of PCT distribution to partial system availability in a form directly usable by PSA analysts. Future work will apply the framework to actual MARS-KS simulation results, extend coverage to additional safety systems, and implement export to AIMS-PSA compatible event tree format (.ket).

---

## REFERENCES

1. IAEA, *Safety Standards Series No. SSG-3*, Vienna, 2010.
2. U.S. NRC, 10 CFR Part 50, Section 50.46, 1974 (amended).
3. F. Di Maio et al., "Reliability Assessment of Passive Safety Systems," *Energies*, **14**(15), 4688, 2021.
4. F. D'Auria et al., "Best Estimate Plus Uncertainty (BEPU): Status and Perspectives," *Nucl. Eng. Des.*, 2019.
5. A. Lye et al., "An Overview of Probabilistic Safety Assessment for Nuclear Safety," *Nuclear Engineering* (MDPI), **5**(4), 2024.
6. KAERI, *MARS-KS Code Manual*, 2019.
