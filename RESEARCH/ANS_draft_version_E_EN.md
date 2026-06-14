# An Automated PRA Post-Processing Tool for Thermal-Hydraulic Simulation Results: From MARS-KS Output to an Interactive Excel DET Dashboard

**[Author Name]**, **[Co-author Name]**
Department of Nuclear Engineering, Kyung Hee University, Republic of Korea
[Email Address]

> Version E — Dashboard/Pipeline Tool Focus, Feedback-Reflected Draft (English)

---

## 1. Introduction

Probabilistic Risk Assessment (PRA) is an essential tool for quantitatively evaluating the safety of nuclear power plants [1]. In PRA, each accident scenario is represented through an event tree (ET), and to quantify the core damage frequency (CDF), each scenario must be converted into a judgment of success or failure of the relevant safety functions. However, a standard ET has a structural limitation in that it classifies each safety function only as a binary success or failure, which limits the detailed review of scenarios involving multi-train safety systems or systems with time-dependent behavior. SMART (System-integrated Modular Advanced ReacTor), the reactor design used for verification in this study, is a 100 MWth integral pressurized water reactor developed by KAERI, equipped with a four-train Passive Residual Heat Removal System (PRHRS) as its key safety system [7]. For a multi-train system such as PRHRS, the number of operating trains (0 to 4) has a direct effect on accident outcomes, yet compressing this into a binary representation discards information about partial system performance.

To overcome this limitation, the Dynamic Event Tree (DET) methodology is emerging as a new approach. A DET retains the discrete number of operating safety-system trains as a branching variable, enabling exploration of how marginal changes in system availability affect the peak cladding temperature (PCT) distribution — sensitivity that cannot be analyzed with a standard ET. However, a DET has far more branches than a standard ET, and each branch condition must be backed by a deterministic thermal-hydraulic (TH) simulation result, so as the number of possible combinations of operating safety-system trains grows, the amount of TH simulation data needed grows exponentially.

The problem then becomes bringing this large volume of TH simulation results back into the PRA and organizing it into event trees. Once the number of scenarios reaches the hundreds, reviewing the individual output files to extract the reactor trip (RT) timing, the operating status of the safety systems, and the PCT — where PCT serves as a surrogate indicator for core damage determination based on the NRC 10 CFR 50.46 criterion (1477 K) [2]) — and converting these consistently into PRA inputs is a task that must be carried out directly by expert personnel who can interpret TH code output and judge the behavior of safety systems. This is not a simple repetitive task but requires a deep understanding of thermal-hydraulic and system characteristics, so the time commitment of senior experts increases linearly with the number of scenarios. As the data volume grows, the probability of fatigue-induced errors also rises, making it difficult to maintain consistent judgments across scenarios [5]. As a result, the larger the simulation scale from adopting a DET, the more the time commitment of expert personnel — i.e., the human cost — increases as well, and the cost of bringing DET results back into the PRA becomes a cost barrier that limits its use.

Therefore, a post-processing capability is needed that can automatically handle the large volume of TH simulation results produced by a DET and convert them into a form that can be used directly in a PRA. Against this background, this study presents an integrated post-processing tool. The tool automatically processes MARS-KS output (Excel) and produces an interactive Excel dashboard, allowing analysts to immediately compare PCT distributions by the number of operating safety-system trains without running additional simulations. This constitutes the first stage of a pipeline that proceeds from TH simulation output, through DET-structure visualization, to the automatic generation of PRA-software-compatible event trees.

---

## 2. Pipeline

The tool is distributed as a single Python script (`psa_analyzer.py`); the user specifies the variable-name file and the scenario files through a GUI file-selection dialog. Once processing is complete, the tool automatically generates a results table (CSV) and an interactive Excel dashboard. The overall pipeline consists of three stages, as shown in Figure 1.

```
[MARS-KS Output Excel] → [Automatic Variable Extraction] → [Interactive Excel Dashboard]
      (Input)                  (psa_analyzer)              (PRA Analyst Interface)
```

The extraction logic common to all five accident types (RT detection, PCT calculation, and the safety-system operation-count judgment algorithm) is implemented only once, in a base class (`BaseAnalyzer`). The accident-type-specific classes (`LOFWAnalyzer`, `SBLOCAAnalyzer`, `GTRNAnalyzer`, `LSSBAnalyzer`, `SGTRAnalyzer`) reuse this common logic as-is, each defining only the parameters specific to its accident type (Floor, aggregation window, wait time, etc.). In object-oriented programming, this structure — which avoids repeating common logic — is called inheritance. Adding a new accident type requires specifying only its parameters, which reduces the likelihood of coding errors and improves maintainability.

The tool's inputs are the MARS-KS output Excel file and a variable-name file that serves as the column-mapping reference for the reactor design. The default is one file per scenario, but multiple scenario files can be selected at once for batch processing. The outputs are a per-scenario results table (CSV: `Scenario`, `Reactor_Trip`, `Safety_System_Count`, `PCT_max`, `PCT_time`, `Outcome`) and, for each accident type, an interactive dashboard (Excel) containing PCT distribution charts filtered by the number of operating safety-system trains, a scenario list, and summary statistics.

In the variable-extraction process, the VarMapper module first parses the variable-name file and uses keyword matching to automatically map columns to their functional roles (safety-system power output, cladding temperature, reactor power). MARS-KS variable-naming formats differ across reactor designs, but when the design changes, only the keyword dictionary needs to be updated — no code changes are required.

The reactor trip (RT) timing is determined as the first instant at which reactor power (rktpow) drops to 20% or below of its initial value. By contrast, a stricter 10% threshold is applied to define the start of the PCT-extraction window, because the two thresholds serve different purposes. The 20% criterion is used to determine whether a trip signal has occurred; immediately after the trip signal, residual power due to inertia persists for tens of seconds. PCT must be extracted during the cooldown phase after this residual-power transient has fully ended, in order to accurately capture the true peak cladding temperature — hence the stricter 10% threshold is used to define the start of the PCT-extraction window. In addition, to avoid the artifact in the first row of MARS-KS Excel output (rktpow = 0), the initial power value is taken as the first positive rktpow value.

For the safety-system operation-count judgment, a representative post-RT power output $Q_i$ is computed for each safety-system train *i*. If the maximum power output across all trains, $Q_{\max}$, is normalized to 100, a train is judged to be not operating when its $Q_i$ is below 10% of that maximum. That is, only trains satisfying

$$Q_i \geq Q_{\max} \times R_{\text{threshold}}$$

are counted as operating, where $R_{\text{threshold}}$ is 10% by default. Unlike a fixed absolute threshold, this relative criterion automatically adapts to scenario-specific variations in thermal load. The accident-type-specific parameters are summarized in Table 1.

**Table 1. Safety-system operation-count judgment algorithm parameters by accident type (all parameters apply to the post-RT interval)**

| Parameter | LOFW | SBLOCA | GTRN | LSSB | SGTR |
|---------|------|--------|------|------|------|
| Aggregation window (post-RT) | Full-time mean | Initial 3 h | Full-time mean | Full-time mean | Full-time mean |
| Wait time (post-RT, s) | 100 | 100 | 100 | 100 | 100 |
| Floor (W) | 1×10⁶ | 1×10⁶ | 1×10⁶ | 1×10⁶ | 1×10⁶ |
| Relative-comparison criterion | 10% | 10% | 10% | 10% | 10% |

> **Note:** The Floor value (currently 1×10⁶ W) may vary depending on the reactor design and thermal-power scale, and must be adjusted by the user when applying the tool to a different design. The wait time, aggregation window, and relative-comparison criterion likewise require review to reflect the transient characteristics of each design.

Floor = 1×10⁶ W is applied uniformly across all accident types. In the analysis of real data, the post-RT power output of an operating train is on the order of several MW at minimum, whereas the residual power of a non-operating train (e.g., a heat exchanger that is not connected) is below several hundred kW — confirming that the two are clearly separated by the 1×10⁶ W threshold.

For SBLOCA, the post-RT safety-system power output starts at several MW and naturally decreases as the decay heat decreases. This is normal behavior driven by the decline of the heat source (decay heat), not a system failure. In actual data, cases with all four trains operating fall below 1×10⁶ W at approximately RT + 11,350–11,600 s. If a full-time average were used, this declining segment's low power values would be reflected in the aggregate, potentially causing the operating-train count to be underestimated. The aggregation window is therefore restricted to an initial 10,800 s (3 h) window starting after the post-RT wait time. Within this window, cases with 1 to 4 operating trains all operate stably at the several-MW level, so the relative-comparison criterion remains valid. The zero-train case (peak power ~2 kW) is clearly separated from the Floor.

PCT extraction and core-damage (CD) determination are performed by extracting the maximum cladding temperature as PCT from the point at which the 10% RT-criterion interval defined above begins. Non-physical outliers exceeding 10,000 K are removed. Per the NRC 10 CFR 50.46 criterion [2]: PCT ≥ 1477 K → CD, PCT < 1477 K → OK.

---

## 3. Excel Dashboard

The interactive Excel dashboard is the tool's core output and serves as the interface that PRA analysts use directly, without any additional coding. It consists of an independent sheet for each accident type, with the following main features.

| Feature | Description |
|------|------|
| Safety-system operation-count filter | Selecting the number of operating trains (0–4) from a dropdown immediately updates the PCT distribution chart |
| PCT distribution visualization | Histogram and summary statistics (min, mean, max, P95) for the selected operation-count condition |
| Scenario list | Displays scenario file names, RT results, PCT, and CD determination for scenarios matching the filter condition |
| Overall distribution comparison | Overlays PCT distributions by operation count to verify monotonicity |

This structure is equivalent to a DET. By defining the number of operating safety-system trains (0–4) as a discrete branching variable — instead of a binary success/failure branch — and directly visualizing the PCT distribution for each state, an analyst can immediately see the effect of a change in success criteria (e.g., relaxing from "3 or more trains" to "2 or more trains") on the core damage frequency, without running additional simulations. Using only the familiar dropdown interface within Excel, analysts can explore the statistics of hundreds of scenarios in real time and perform sensitivity analyses of success criteria without installing any additional software or having coding knowledge.

---

## 4. Results

For algorithm verification, actual MARS-KS simulation results were used. RT detection and safety-system operation-count judgment results were compared against manually reviewed values across all five accident types, and both algorithms achieved 100% agreement. However, the simulation data currently available is of limited scope, confined to the design-basis-accident range, and safety-system behavior in the upper (high-temperature) region of the PCT distribution has not been sufficiently captured. In particular, the diversity of thermal-hydraulic behavior beyond the interval where initial safety-system power output dominates is not adequately represented in the data, so verification of the algorithm in this region will be carried out after large-scale simulations are performed in the future.

Because the available simulation data is limited in scope and concentrated in the interval where safety-system power output dominates, it is not well suited for demonstrating the dashboard's PCT-distribution filtering functionality across the full range. To address this, a synthetic demo dataset of 1,000 scenarios — 200 for each of the five accident types — was generated separately. The dataset was constructed with a balanced distribution across operation-count levels and RT outcomes, and includes CD scenarios as well. Dataset quality was verified against four physical-consistency rules: PCT–outcome consistency (1477 K threshold), safety-system monotonicity (PCT decreases as the operation count increases), the ATWS penalty (PCT increases when RT fails), and the Feed-and-Bleed operating-condition constraint; across all 1,000 scenarios, zero rule violations were found.

**Table 2. Summary of tool performance**

| Item | Verification basis | Result |
|------|---------|------|
| RT detection | Actual MARS-KS data, manual comparison, 5 accident types | 100% agreement |
| Safety-system operation-count judgment | Actual MARS-KS data, manual comparison, 5 accident types | 100% agreement |
| PCT extraction | Actual data (within design-basis range) | Further verification planned after large-scale simulations |
| Synthetic demo dataset consistency | 4 physical rules, 1,000 scenarios | 0 violations |
| Processing time | 1,000 scenarios, standard PC | < 30 s |

As an example of dashboard usage, Fig. 1 shows, for the synthetic demo dataset, how the PCT distribution changes in the LSSB dashboard as the number of operating safety-system trains is selected sequentially from 0 to 3. A tendency for the PCT distribution to shift toward lower values as the operation count increases can be observed visually. Based on this distributional shift, an analyst can quantitatively estimate, without additional simulation, the impact on safety of relaxing the current success criterion (e.g., "2 or more trains operating") to "1 or more trains operating".

> *[Figure 1: LSSB dashboard — PCT distribution comparison chart by safety-system operation count, to be inserted]*

---

## 5. Conclusion

This study presented a tool that automatically converts MARS-KS TH simulation output into an interactive Excel dashboard directly usable for PRA analysis. The tool is distributed as a single Python script and, through GUI-based file selection alone, performs RT detection, safety-system operation-count judgment, PCT extraction, CD determination, and dashboard generation in a single batch. The tool's core contribution is the interactive Excel dashboard, which adopts a DET structure that defines the number of operating safety-system trains as a discrete branching variable, providing an environment in which analysts can immediately explore the sensitivity of success criteria without additional simulation. Thanks to its Excel-friendly interface, the PCT distributions of hundreds of scenarios can be compared and analyzed in real time without any coding knowledge.

The relative-comparison-based safety-system operation-count judgment algorithm provides classification that is robust to changes in initial conditions, and the VarMapper module provides extensibility, allowing it to be reapplied without code modification when the reactor design changes. Across 1,000 demo scenarios, the physical consistency of all extracted variables was confirmed, and the processing time was under 30 seconds.

Future work includes full-range verification of the algorithm through application to a large volume of actual MARS-KS simulation results, extension to additional safety systems such as ADS, PSIS, and SIT, and implementation of direct output of the tool's results in the AIMS-PSA-compatible event-tree (ET) file format (.ket). The ultimate goal of the completed pipeline is to post-process large-scale TH simulation data and generate it directly as a .ket file, so that analysts do not need to manually construct an event tree from the TH data themselves but can instead open the resulting .ket file in AIMS-PSA and immediately view the completed event-tree structure — i.e., an integrated post-processing framework built around this capability.

---

## References

1. IAEA, *Safety Standards Series No. SSG-3*, Vienna, 2010.
2. U.S. NRC, 10 CFR Part 50, Section 50.46, 1974 (amended).
3. F. Di Maio et al., "Reliability Assessment of Passive Safety Systems," *Energies*, **14**(15), 4688, 2021.
4. F. D'Auria et al., "Best Estimate Plus Uncertainty (BEPU): Status and Perspectives," *Nucl. Eng. Des.*, 2019.
5. A. Lye et al., "An Overview of Probabilistic Safety Assessment for Nuclear Safety," *Nuclear Engineering* (MDPI), **5**(4), 2024.
6. KAERI, *MARS-KS Code Manual*, 2019.
7. KAERI, *SMART Standard Design Approval Document* (Report No. TBD), KAERI, Republic of Korea.
