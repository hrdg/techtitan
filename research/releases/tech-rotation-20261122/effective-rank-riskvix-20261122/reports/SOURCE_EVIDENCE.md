# Source mechanism

Original paper: **Industry Rotation and Time-Varying Sensitivity by VIX**.

The source mechanism estimates industry-return sensitivity to changes in VIX and
shows that the sensitivity varies with the VIX regime. The local extension keeps
that mechanism at the industry layer:

```text
industry return = intercept + beta * change in VIX + residual
```

The PDF is not redistributed. The project-side copy used for the experiment has
SHA256:

```text
69edcec403b5c975dfd9251c89dbf0da02712d548af89a70034746fe51ff83cc
```

This note records the mechanism used by the implementation; it is not a claim
that the 18-industry A-share test is an exact reproduction of the paper's
sample, portfolio construction, or reported performance.
