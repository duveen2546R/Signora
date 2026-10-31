# Statistical design and testing methods to increase power and robustness of a suit-vs-video equivalence claim

Scope: designs and procedures that could legitimately strengthen the SignSure claim that an IMU suit and a
two-phone video measurement of nine upper-body joint-angle curves agree within a ±15° RMS margin. The current
method (one take per sign, pre-sign-hold offset removal, parametric-bootstrap Monte Carlo, RMS primary claim,
fixed-sequence testing over nine angles) is taken as given. Notes on sources: several statistical primary papers
(Bland & Altman 2007, Wiens & Dmitrienko 2005, Bretz et al. 2009, Røislien's functional LoA, Serrien et al. 2019)
could not be read in full here; where the finding comes from an abstract, a secondary page or a package vignette
this is stated.

## 1. Multiple-testing procedures for nine equivalence endpoints (alternatives to a strict fixed sequence)

### Takeaway
A strict fixed sequence wastes all remaining alpha as soon as one early angle (shoulder elevation) fails. The
fallback procedure and, more generally, the Bretz et al. graphical approach keep strong familywise error control
but let later angles (elbows) still be claimed after an early failure; Holm is the order-free option for an
order-uncertain set. If the only claim wanted is "all nine agree", the intersection-union principle needs no
multiplicity adjustment at all, but then nothing can be claimed for individual angles when any one fails. All of
these must be fixed before analysing a new take.

### Cited Findings
- Fallback procedure (Wiens & Dmitrienko 2005, *J Biopharm Stat*): splits alpha across hypotheses in a pre-set
  order; it was found to be "a viable alternative to fixed-sequence testing when there is doubt about
  first-hypothesis power"; its validity is shown via closed testing. — [search summary of the paper / related SAP](https://metricgate.com/docs/fallback-procedure) (secondary; primary not retrieved)
- Difference from fixed sequence: a fixed-sequence test stops at the first non-rejection, whereas the fallback
  reserves a small alpha for the next test even if the previous hypothesis is not rejected. — [Clinical trial SAP, NCT03336242](https://cdn.clinicaltrials.gov/large-docs/42/NCT03336242/SAP_001.pdf)
- Fallback mechanics as described by secondary sources: each hypothesis gets a pre-set minimum share w_i·α; its
  local level is w_i·α plus the predecessor's level if the predecessor was rejected; weights sum to 1 and must be
  fixed before unblinding. The fixed-sequence test is the special case where the first hypothesis gets all of
  alpha. — [MetricGate (non-peer-reviewed)](https://metricgate.com/docs/fallback-procedure); [arXiv 2402.13719](https://arxiv.org/pdf/2402.13719)
- Graphical approach (Bretz, Maurer, Brannath & Posch 2009, *Statistics in Medicine* 28:586–604): hypotheses are
  nodes of a directed weighted graph; each procedure is a shortcut to a closed test built from weighted Bonferroni
  tests and strongly controls FWER at α; it contains Bonferroni, Holm, fixed-sequence, fallback and serial/parallel
  gatekeeping as special cases; the rejection order does not affect the final decisions. Extended to weighted
  Simes and parametric tests (Bretz et al. 2011, *Biometrical Journal*). R package `graphicalMCP` implements it. — [arXiv 1908.10262 / search summary](https://arxiv.org/pdf/1908.10262); [graphicalMCP vignette](https://cran.nics.utk.edu/cran/web/packages/graphicalMCP/vignettes/shortcut-testing.Rmd)
- Fallback tests for co-primary endpoints (Ristl, Frommlet, Koch & Posch 2016, *Statistics in Medicine*
  35:2669–2686): keep the classical "all endpoints significant" rejection region but additionally allow
  rejection of individual hypotheses when not all endpoints succeed (uniform improvement); built as closed tests.
  Hierarchical tests are fallback tests but require a prespecified order and had up to ~10 percentage points less
  disjunctive power than non-hierarchical tests at small-to-moderate correlation. Hochberg and Hommel are fallback
  tests but only shown conservative for non-negative correlations. Example with p = 0.01, 0.02, 0.03: a
  "2-out-of-3" test rejects H1 at 0.025 while the classical test and Bonferroni–Holm reject nothing. The paper does
  not treat equivalence testing. — [PMC5069608](https://pmc.ncbi.nlm.nih.gov/articles/PMC5069608)
- Ristl et al. power numbers (α = 0.025, three endpoints, equal effects δ=3): conjunctive power 61.4% (2-out-of-3)
  vs 60.0% (Bonferroni–Holm) at ρ=0, 78.5% vs 75.2% at ρ=0.9; Holm had higher power to reject at least one
  hypothesis (97.9% vs 93.7%). — [PMC5069608](https://pmc.ncbi.nlm.nih.gov/articles/PMC5069608)
- Intersection-union test (Berger & Hsu 1996, *Statistical Science* 11:283–319): if each component rejection region
  has level α, the intersection has level α, so a conjunctive claim ("all components equivalent") needs no
  multiplicity correction; TOST is itself an IUT. — [Statistical Science](https://projecteuclid.org/euclid.ss/1032280304); [HiSET restatement, arXiv 1810.03586](https://arxiv.org/pdf/1810.03586); [Dobson & Murphy (ASTM) secondary](https://cdn-aorpci7.actonsoftware.com/acton/cdna/9652/f-14b4d774-faa2-4d11-853f-54310ca55406/0/0)
- In equivalence settings requiring all co-primary endpoints, power falls as endpoints are added (chance of failing
  at least one rises). — [SimTOST vignette](https://cran.nics.utk.edu/cran/web/packages/SimTOST/vignettes/intropkg.html); [Ristl 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC5069608)

### Inferences
- Which procedure suits an order-uncertain set of nine angles:
  - **Holm on the nine per-angle TOST/RMS-bound p-values** is valid under arbitrary dependence (it is a graph with
    equal weights and full alpha propagation), needs no order, and an early doubtful angle cannot block the others.
    Cost: the smallest p-value must beat α/9 ≈ 0.0056 at α=0.05. With strongly correlated left/right angles this is
    conservative.
  - **Graphical procedure with tiers** is the closest to the current pre-registered intent: e.g. trunk gets an
    initial weight, each bilateral pair splits its weight between left and right with edges passing alpha
    left↔right and then onward, and "fallback" edges let alpha from a failed tier flow on. This keeps the
    scientific priority of trunk → shoulders → elbows → wrists while not stopping at the first failure. Any
    weights must be chosen before the take is analysed; a tool like `graphicalMCP` can simulate power under the
    Monte Carlo's per-angle power estimates to choose them.
  - **Weighted parametric (maxT-type) graphical tests** (Bretz 2011) can exploit the joint distribution of the nine
    statistics, which the project's Monte Carlo already produces (each draw yields all nine RMS values). Using the
    simulated correlation to set local critical values would recover most of the Holm/Bonferroni conservatism. This
    needs the correlation to be estimated under the null configuration (at the margin), which the parametric
    bootstrap can approximate; validity should be confirmed by the existing simulation harness
    (`single_take_simulation.py`).
  - **Hochberg/Hommel**: not recommended without checking; validity requires positive dependence (PRDS) and the
    RMS-upper-bound statistics are derived quantities whose dependence sign is not guaranteed (Ristl: only shown
    conservative for non-negative correlation).
  - **IUT / conjunctive claim**: if the headline claim is "the suit agrees with video on all nine angles", each
    angle can be tested at full α with no adjustment; but power is roughly the product of nine per-angle powers and
    a single failure kills the global claim; it also licenses no individual-angle claims on its own. A fallback
    test in the Ristl sense (classical co-primary region + individual rejections) gives both.
- Power implication for the current problem (shoulder elevation doubtful, elbows passing): under fixed sequence the
  elbows get zero alpha after a shoulder failure; under fallback/graphical/Holm they keep at least their initial
  share (e.g. α/9 to α/3 depending on weights), so a strongly passing elbow (upper bound far below 15°) would
  still be confirmable.
- Pre-registration status: switching procedure is **only confirmatory for takes analysed after a dated commit**
  changing `equivalence_margins.json`. Re-analysing After/Action with Holm or a graph is exploratory (same status
  the CLAUDE.md already assigns to the testing order). Reporting all nine unadjusted per-angle bounds as
  descriptive results is always legitimate post hoc if labelled as such.

### Gaps
- Full text of Wiens & Dmitrienko (2005) and Bretz et al. (2009) not retrieved; weight-update formulas above come
  from secondary sources.
- No source found that studies graphical/fallback procedures specifically for equivalence (TOST/RMS-bound)
  endpoints with derived statistics; validity rests on closed-testing theory plus the project's own simulation.

## 2. From one take to several takes, signs and performers: repeated-measures agreement, TDI/CCP, CCC, pooling

### Takeaway
Generalisation needs replication at the take (and ideally signer) level, analysed with a mixed model whose
independent unit is the take, not the frame. Mixed-model limits of agreement, total deviation index (TDI) and
coverage probability (CP) are the standard repeated-measures agreement tools; CP is recommended alongside raw
plots, CCC should not be used alone. Note that LoA/TDI-type claims ("95% of differences within ±15°") are much
stricter than the current RMS claim and need SD of differences ≲ 7.6°. With take-level RMS as the outcome, a few
to ~15 takes per sign suffice depending on between-take variability (rough calculation below).

### Cited Findings
- Bland & Altman (2007), "Agreement between methods of measurement with multiple observations per individual",
  *J Biopharm Stat* 17(4):571–582: separates between- and within-individual variation; treating replicate pairs as
  independent gives limits of agreement that are too narrow. — [York PDF](https://www-users.york.ac.uk/%7Emb55/meas/bland2007.pdf); [White Rose 2006 version](https://eprints.whiterose.ac.uk/3411/1/Bland_2006_Agreement.pdf) (full text not machine-readable here; content from abstracts/snippets)
- Parker, Scott, Inácio & Stevens (2020, *BMC Med Res Methodol* 20:154) tutorial: CCC, LoA, TDI, CP and the
  coefficient of individual agreement (CIA) can all be computed from linear mixed models (random subject,
  activity and interaction effects; fixed device effect). CP and TDI are based on the mean squared deviation (MSD)
  combining fixed bias and variance components. Recommendations: use CP alongside a graphical display of raw data;
  "The CCC should not be used as a sole agreement metric"; report variance components and bias; pre-specify the
  model and the acceptable difference; methods may perform poorly with few subjects or repeats; do not test for
  clustering and then ignore it. The tutorial treats replicates as independent given the factors and does not model
  autocorrelation. — [PMC7291585](https://pmc.ncbi.nlm.nih.gov/articles/PMC7291585/)
- CCC is inflated by between-subject/between-activity variance and can look high even with poor within-subject
  agreement; CIA depends mainly on within-device variance. — [Parker et al. 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7291585/)
- TDI (Lin 2000) is the p0-th percentile of |D|; CP (Lin et al. 2002) is the probability that |D| < δ0;
  Choudhary extended TDI to repeated measures and generalised tolerance-interval agreement to repeated-measurement
  data (Choudhary 2007; Choudhary & Nagaraja, *Measuring Agreement*, Wiley 2017). — [Escaramís et al. 2010 / PMC2859350](https://pmc.ncbi.nlm.nih.gov/articles/PMC2859350); [Choudhary 2007 preprint](https://personal.utdallas.edu/~pankaj/choudhary_2007_JSPI_preprint.pdf); [Wiley book page](https://wiley-vch.de/de/fachgebiete/mathematik-und-statistik/measuring-agreement-978-1-118-07858-7)
- Tolerance limits (Francq, Berger & Boachie 2020, *Stat Med*; Francq, Lin & Hoyer 2019, *Stat Med*): a confidence
  limit on a prediction interval of differences; R package SimplyAgree supports nested/repeated data via `nlme::gls`
  with an `id` grouping and a `time` argument for repeated/time-series data, with approximate or parametric-bootstrap
  tolerance limits. — [SimplyAgree vignette](https://cran.nics.utk.edu/cran/web/packages/SimplyAgree/vignettes/agreement_analysis.html)
- Sample size for Bland–Altman agreement (Lu et al. 2016, *Int J Biostat* 12(2)): inputs α, β, expected mean and SD
  of differences and the maximum allowed difference Δ, which must exceed mean + 1.96·SD; n is chosen so the CI of
  the limits lies inside ±Δ with the target power. MedCalc example: mean 0.001167, SD 0.001129, Δ 0.004, α 0.05,
  power 80% → n = 83. — [MedCalc manual](http://www.medcalc.org/en/manual/sample-size-bland-altman.php); [IDEAS record](https://ideas.repec.org/a/bpj/ijbist/v12y2016i2p8n5.html)
- Pooling across studies/signs: random-effects prediction intervals (IntHout, Ioannidis, Rovers & Goeman 2016,
  *BMJ Open* 6:e010247) — in 479 significant Cochrane random-effects meta-analyses with heterogeneity, the 95%
  prediction interval included null or opposite effects in 72.4%; τ² and the prediction interval are imprecise with
  few small studies. — [BMJ Open](https://bmjopen.bmj.com/content/6/7/e010247)

### Inferences
- **Estimand matters.** The current RMS claim is √MSD (Lin's MSD on the curve). A LoA/TDI_0.95 claim bounds the
  95th percentile of |difference|; for zero-mean normal differences TDI_0.95 ≈ 1.96·RMS, so "TDI_0.95 < 15°" needs
  RMS ≲ 7.6°, whereas the existing protocol passes at ~9°. CP(15°) is a useful complementary descriptive. Changing
  the primary estimand to LoA would reduce, not increase, power; keep RMS (or MSD) as primary and report LoA/TDI/CP
  as secondary.
- **Unit of replication.** Frames within a take are not replicates (effective n ≈ 2–7). The natural mixed model is
  per-angle take-level summaries (MSD_k or RMS_k, k = takes) with random effects for sign and signer, or a curve
  model with take random effects and an AR/continuous-time residual. The Parker/Bland–Altman models assume
  conditional independence of replicates, so frame-level use would repeat the autocorrelation problem.
- **Rough sample sizes (own calculation, assumptions stated).** Treat each take's per-angle RMS (after offset
  removal and Monte Carlo bias correction) as one observation; test population mean RMS < 15° with a one-sided
  t-test (α = 0.05, power 80%, z sum ≈ 2.93). n ≈ (2.93·σ_b/(15 − μ))² plus ~1–2 for t:
  - μ = 9°, between-take SD σ_b = 3° → ≈ 2–4 takes;
  - μ = 9°, σ_b = 5° → ≈ 6–8 takes;
  - μ = 11°, σ_b = 5° → ≈ 13–15 takes;
  - μ = 12°, σ_b = 4° → ≈ 15–17 takes.
  σ_b must come from a pilot (it includes keypoint noise, calibration variation and genuine performance
  differences). Each take's own within-take uncertainty adds to σ_b. A random-effects model across signs further
  needs enough signs to estimate τ²; IntHout et al. warn prediction intervals are imprecise with few studies, so a
  population-of-signs claim realistically needs ≥ ~10 signs; with fewer, report sign-specific results plus a
  fixed-effect pooled estimate, labelled as conditional on those signs.
- **Meta-analytic equivalence across signs.** Two legitimate framings: (a) fixed-effect pooled RMS across a
  pre-specified set of signs (claim about that set; more power), (b) random-effects mean plus a prediction interval
  for a new sign (claim about signs in general; the prediction interval must sit below 15°, which is much harder).
- **Pre-registration:** the number of takes, the model (random effects, covariance), the estimand and the pooling
  rule must be pre-specified; adding takes until a pass occurs is optional stopping unless a group-sequential
  design (e.g. Maurer–Bretz graphical group-sequential extension) is pre-registered.

### Gaps
- Bland & Altman 2007's exact variance-component formulas and sample-size remarks could not be extracted (PDF text
  not readable here).
- No source found giving sample-size tables for TDI/CP with repeated measures or for RMS-based equivalence across
  takes; the numbers above are back-of-envelope.
- No meta-analytic equivalence (TOST on pooled effects) paper specific to method agreement was retrieved.

## 3. Functional (curve) approaches: functional LoA, SPM, functional equivalence

### Takeaway
Functional limits of agreement and SPM-type inference exist and have been used for IMU-vs-optical comparison, but
they need replicate curves (subjects or takes), not one take; SPM power analyses suggest ~5–40 independent units
for 0.8 power. For a single take they add little beyond the project's existing whole-curve band; for multi-take
designs they are the natural secondary analysis to show *where* in the sign agreement breaks down.

### Cited Findings
- Olsen, Pfau & Ritz (2013, *J Biomech*) applied functional data analysis and "functional limits of agreement" to
  compare IMU-derived and motion-capture distal-limb displacement in seven horses; accuracy/precision were ≤5% of
  range of motion for cranio-caudal and vertical position, while latero-medial position during walk had 10% average
  and 111% maximum error; they argue FDA and functional LoA are sensitive for cyclical data. — [KU research record](https://test01.ku.dk/:obvius/pureproxy/3974268/en/publications/functional-limits-of-agreement-applied-as-a-novel-method-comparis)
- Review of test-retest reliability measures for curve data (Pini, Schelin et al., *Sports Biomechanics*): covers
  functional LoA, coefficient of multiple correlation, distance/similarity measures and integrated pointwise indices;
  recommends integrated ICC and standard error of measurement because they account for between-person variation;
  R code supplied. — [SPONET record](https://sponet.de/sponet/Record/4059738)
- SPM uses random field theory exploiting smoothness to control multiplicity over the 1D domain; ROI analyses are
  valid for arbitrary (even broken) regions and ROIs pre-specified from pilot data can detect smaller effects than
  full-domain 1D tests (Pataky, Robinson & Vanrenterghem 2016, *PeerJ*). — [PeerJ 2652](https://peerj.com/articles/2652); [LJMU PDF](https://researchonline.ljmu.ac.uk/4852/1/2016%20Pataky%20PeerJ%20Region%20Of%20Interest%20%2B%20Appendix.pdf)
- 1D power (power1d; Pataky, Robinson & Vanrenterghem 2018, *J Biomech* 66): power ~0.8 reachable with ~5 subjects
  (within-subject minimum-jerk) and ~10 (between-subject knee kinematics). Robinson, Vanrenterghem & Pataky (2021,
  *J Biomech* 122): sample-size estimation in ~4% of 653 papers; 1D estimates needed ~5–40 participants for 0.8
  power and were always larger than 0D estimates. — [LJMU 7610](https://researchonline.ljmu.ac.uk/id/eprint/7610/); [LJMU 14792](https://researchonline.ljmu.ac.uk/id/eprint/14792/)
- Comparison of interval-wise testing, SPM, SnPM and Benjamini–Hochberg for functional sports-biomechanics data
  (Pini/Pataky et al. 2021). — [Unicatt record](https://publires.unicatt.it/it/publications/simultaneous-inference-for-functional-data-in-sports-biomechanics/)

### Inferences
- A functional equivalence claim ("the whole difference curve lies inside ±δ") is an IUT over the domain: it
  requires a simultaneous band (as the project already computes), which is the most demanding claim; the project's
  finding that it needs ~1 px noise is consistent with that.
- With K takes of the same sign, time-normalised (and if needed registered) difference curves allow functional LoA
  (mean curve ± k·SD curve with simultaneous coverage) and SPM one-sample tests against ±δ (two one-sided SPM
  t-tests = a functional TOST). These treat take as the unit, so autocorrelation within the curve is handled by the
  smoothness/RFT machinery rather than by counting frames. Expect ~5–40 takes for adequate power by analogy with
  the power1d results.
- A pre-registered ROI (e.g. the stroke phase of the sign, defined from the FBX wrist-speed window) can increase
  power relative to whole-curve inference — legitimate only if defined before analysis.
- Time registration of curves across takes is an analysis choice that must be pre-specified (it can mask timing
  disagreement).

### Gaps
- Røislien's functional LoA paper (believed to be in *Statistics in Medicine*) could not be located in searches;
  its formulas and coverage properties are unverified here.
- No peer-reviewed SPM "equivalence test" (functional TOST) paper was found; only a vector-field SPM paper
  mentioning "non-directed" equivalence-type nulls, and Bayesian SPM (section 5).

## 4. Handling definition offsets / bias

### Takeaway
Agreement literature consistently recommends reporting bias (systematic offset) and random disagreement
separately, and pre-specifying any correction. The project's rest-hold offset rule is a form of calibration;
robustness improves if the offset is estimated from data independent of the tested window (separate static and
functional calibration poses/takes) and if its estimation uncertainty is propagated (already done in the Monte
Carlo). Errors-in-variables thinking applies because neither system is a gold standard.

### Cited Findings
- Report variance components and bias estimates alongside agreement indices so the source of disagreement is
  visible; pre-specify the model in an analysis plan. — [Parker et al. 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7291585/)
- Bland: ordinary least squares regression "ignores the error in x", so a slope different from 1 does not prove
  disagreement; a non-significant paired t-test does not show agreement; LoA assume constant bias and SD across
  magnitude, otherwise crude limits misfit (glucose example: too wide at one end, too narrow at the other). — [Bland, Oxford talk](https://www-users.york.ac.uk/~mb55/talks/oxtalk.htm)
- Large systematic offsets are typical of IMU-vs-optical upper-limb comparisons: a commercial IMU vs optical
  shoulder study found bias 1.2°–50.7° and RMSE 9.7°–20.3° in simple movements (Henschke et al. 2022). — [Li et al. 2024 / search summary](https://doaj.org/article/24eac5c80eb846fd89831b1a1346372c)
- Poitras et al. note the biomechanical (upper-limb) model choice adds variability and partly explains the large
  shoulder error range. — [Poitras et al. 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6479822/)

### Inferences
- Options, with validity status:
  1. **Report raw RMS, offset, and offset-corrected RMS separately** (already done). Always legitimate; the claim
     wording must say "after removing a constant per-angle definition offset".
  2. **Independent calibration data**: record a dedicated static pose (and a slow elbow-bend / arm-raise functional
     calibration) in a separate take or segment, and estimate offsets only from that. This avoids any dependence
     between offset estimation and the tested window and makes the offset a property of the setup, which is
     testable for stability across takes. Must be pre-registered as the offset rule before use.
  3. **Offset as a nuisance with an a-priori bound**: report the offset with its CI and pre-specify a maximum
     plausible definition offset per joint (from anatomy, e.g. carrying angle), flagging takes outside it.
  4. **Include bias in the margin** (no offset removal, i.e. test raw RMS): the most conservative and the most
     interpretable for end use (the avatar sees raw angles), but with 5–24° offsets it is expected to fail; it is
     the right claim only if the product actually consumes raw suit angles without calibration.
  5. **Errors-in-variables / Deming-type models across takes** separate a constant offset from proportional
     disagreement (slope ≠ 1, e.g. range compression in video). Requires several takes or a wide range of angles;
     cannot be identified from one still hold. Not usable post hoc to rescue a failed confirmatory test.
- Multi-take designs allow testing whether the offset is constant across takes/signs (random offset variance ≈ 0),
  which is itself evidence that the offset is a definitional rather than a tracking difference.

### Gaps
- No peer-reviewed source was retrieved on sensor-to-segment / functional calibration accuracy for Rokoko or
  similar suits, or on the magnitude of anatomical definition offsets (carrying angle) between skeleton models.
- No source found on formal errors-in-variables equivalence tests for joint-angle curves.

## 5. Bayesian equivalence (ROPE, posterior probabilities) for single- or few-take designs

### Takeaway
Bayesian ROPE/posterior-probability decisions re-express the same evidence; with flat priors they are close to the
frequentist interval decisions and give no real power gain. Legitimate gains come only from informative priors that
are justified independently (e.g. a pre-registered prior on the error model from earlier takes, or hierarchical
borrowing across signs), and the decision rule has known logical critiques. They do not fix the effective-n problem.

### Cited Findings
- Kruschke HDI+ROPE rule: accept if the 95% HDI lies entirely inside the ROPE, reject if entirely outside,
  otherwise undecided; variant "ROPE-only" rule accepts if >95% of the posterior is inside the ROPE; 89% HDIs are
  sometimes used for stability. — [CASRAI guide](https://casrai.org/guides/region-of-practical-equivalence-rope); [LMU technical report](https://epub.ub.uni-muenchen.de/74222/1/TR%20ROPE%2BHDI%20SUBMITTED.pdf)
- Critiques: the HDI+ROPE rule has been argued to be logically incoherent (Etz et al.); the ROPE-only rule depends
  on arbitrary loss values; others argue for using the posterior probability of the ROPE or Bayes factors for
  interval nulls. — [Etz et al. draft, NSF PAR](https://par.nsf.gov/servlets/purl/10562001); [LMU report](https://epub.ub.uni-muenchen.de/74222/); [arXiv 1903.03153](https://arxiv.org/pdf/1903.03153)
- Bayesian SPM (Serrien, Goossens & Baeyens 2019, *International Biomechanics* 6(1):9–18): Bayes factors and
  posterior probabilities with default priors (BayesFactor R package) for 1D biomechanical data, motivated by
  quantifying evidence for the null (e.g. left–right gait symmetry). — [PMC8211129](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8211129/); [DOAJ](https://doaj.org/article/01a33a6d0c5d4609b245fb3f1edad698)
- Neuroimaging guidance: claiming a null region needs strong Bayes-factor support for the null (BF ≈ 20 cited as
  strong). — [Penny & Ridgway 2013, PMC3606143](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3606143/)

### Inferences
- In the single-take setting the likelihood is dominated by the externally estimated noise model and the
  autocorrelated curve; a Bayesian analysis with vague priors yields a posterior for RMS close to the bootstrap
  distribution, so the posterior probability P(RMS < 15°) ≈ 1 − (one-sided p), i.e. no free power.
- Legitimate uses: (a) a hierarchical model across takes/signs/signers, which partially pools per-sign RMS and
  gives a principled predictive distribution for a new sign; (b) pre-registered informative priors on noise and
  calibration parameters derived from *other* takes (not the analysed one); (c) reporting P(RMS < 15°) as an
  interpretable complement. Priors chosen after seeing the take, or ROPE widths tuned post hoc, are not legitimate.
- Bayesian decisions do not carry frequentist error guarantees by default; if presented as a confirmatory test,
  their operating characteristics (false equivalence at the margin) should be checked with the existing simulation
  harness, as was done for the current RMS bound.

### Gaps
- Full text of Serrien et al. 2019 not readable (PMC verification page); its priors, thresholds and small-sample
  behaviour are unverified here.
- No source found applying Bayesian equivalence to method-agreement studies with autocorrelated curves.

## 6. Margin justification per joint

### Takeaway
IMU-vs-optical literature reports wide per-joint error ranges for the upper limb (shoulder up to tens of degrees,
elbow 0.2–30.6°, wrist 2.2–30°, trunk 1.8–5.9° in good studies) and grades RMSE <5° excellent and 5–10° good. A
uniform ±15° RMS margin is therefore lenient relative to "good" validity for trunk and elbow, roughly in line with
typical shoulder results, and possibly tight for wrist deviation. Joint-specific margins (e.g. tighter trunk/elbow,
looser wrist) are defensible but must be fixed before new takes; no sign-language-specific "meaningful difference"
threshold was found.

### Cited Findings
- Poitras et al. (2019, *Sensors* 19:1555), systematic review of 42 studies: shoulder RMSE 0.2–64.5° (simple
  1–21°, complex 5–64.5°; flexion/extension ≤15°, abduction <20°, rotation 1–60°); elbow RMSE 0.2–30.6°; wrist
  2.2–30° (ulnar deviation 3–30°, flexion 3–20°); trunk 1.8–5.9° excluding two low-quality studies. Error
  thresholds: <5° excellent, 5–10° good (citing Cuesta-Vargas et al. 2010). Validity better for simple tasks and
  for lower-limb joints; upper-limb evidence "conflicting" for complex multi-axis movements. — [PMC6479822](https://pmc.ncbi.nlm.nih.gov/articles/PMC6479822/)
- Li et al. (2024, *Wearable Technologies*) meta-analysis (51 articles, 16 pooled): excellent concurrent validity
  for shoulder and elbow flexion–extension; caution for shoulder rotation and wrist ulnar–radial deviation. — [DOAJ](https://doaj.org/article/24eac5c80eb846fd89831b1a1346372c)
- Henschke et al. (2022, *Health Sci Rep*): commercial IMU vs optical shoulder, ICC 0.040–0.733, RMSE 9.7–20.3°,
  bias 1.2–50.7° in simple movements; insufficient agreement in complex movements. — [via Li et al. search summary](https://doaj.org/article/24eac5c80eb846fd89831b1a1346372c) (secondary)
- Robert-Lachaine et al. (2017): full-body Xsens vs Optotrak in 12 participants; technological error under 5° RMSE
  during handling tasks. — [IRSST record](https://pharesst.irsst.qc.ca/etudes-primaires/139)
- A recent review reports Xsens-based validation studies with angle RMSEs of ~2.6–7.7°. — [arXiv 2401.12919](https://arxiv.org/pdf/2401.12919)
- Note the comparison here is suit vs *markerless video*, not vs optical markers; the review figures describe IMU
  error against a stronger reference.

### Inferences
- Joint-specific margin proposal (for a future pre-registration, to be justified in writing): trunk twist ~10°
  (good IMU validity, small trunk ROM in signing), elbow flexion ~10–15°, shoulder elevation/abduction ~15°, wrist
  deviation ~15–20° (both IMU and video are weakest here). Tighter margins lower power; looser ones weaken the claim.
  A more principled anchor would be the perceptual/linguistic tolerance of ISL signs (how much angle change changes
  sign recognisability), which would require a perception study.
- Because the reference is markerless video with its own ~3 px keypoint noise, the achievable agreement is bounded by
  combined error of both systems; the existing finding (pass needs true RMS ≲ 9° at 3 px noise) means margins below
  ~12° are unlikely to be passable with the current recording protocol.
- Margins can be **reported** post hoc as sensitivity analyses (e.g. "the upper bound for elbow was 8.3°, which
  would pass any margin ≥ 8.3°") — the upper bound itself is margin-free — but the confirmatory decision must use
  the pre-registered margin.

### Gaps
- No peer-reviewed minimal clinically/linguistically important difference for joint angles in sign language was
  found.
- Exact per-joint RMSE values from Robert-Lachaine 2017 (shoulder/elbow/wrist) were not retrieved.
- No suit-vs-markerless-video (as opposed to suit-vs-optical) per-joint RMSE benchmark was retrieved.
