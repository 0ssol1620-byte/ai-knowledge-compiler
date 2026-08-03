# FOLYNTA v1 official source freeze — 2026-08-03

This registry records current official upstream identities inspected for the
2026-08-03 masterplan. It is a source freeze, not a promotion decision. Model
weights, runtime images, datasets, and licenses still require the candidate
registry's exact identity and approval gates.

| Source                | Official repository        | Frozen revision                            | License metadata              | Decision                                                                                       |
| --------------------- | -------------------------- | ------------------------------------------ | ----------------------------- | ---------------------------------------------------------------------------------------------- |
| OmniDocBench          | `opendatalab/OmniDocBench` | `193627ae9e97d89188468ed1ee3b7a856ff76044` | Apache-2.0                    | Benchmark source only; upstream README identifies v1.7, superseding the masterplan's v1.6 note |
| ParseBench            | `microsoft/parsebench`     | `1d460294b3b9c57fb3fa944dc17a9c044c24d1e5` | Apache-2.0                    | Benchmark source only                                                                          |
| olmOCR / olmOCR-Bench | `allenai/olmocr`           | `f7cfe4c22098b154c76b6ec950d1c0a464eecf8d` | Apache-2.0                    | Benchmark and candidate source only                                                            |
| PaddleOCR             | `PaddlePaddle/PaddleOCR`   | `2661c7c0`                                 | Apache-2.0                    | Candidate remains unpromoted                                                                   |
| MinerU                | `opendatalab/MinerU`       | `79d6d8d`                                  | GitHub metadata `NOASSERTION` | License hard gate remains open                                                                 |
| DeepSeek-OCR2         | `deepseek-ai/DeepSeek-OCR` | `2f3699e`                                  | Apache-2.0                    | Candidate remains unpromoted                                                                   |
| dots.mocr             | `studio-dots-ai/dots.mocr` | `23f3e56`                                  | MIT                           | Candidate remains unpromoted                                                                   |
| MonkeyOCR             | `Yuliang-Liu/MonkeyOCR`    | `7aace39`                                  | Apache-2.0                    | Candidate remains unpromoted                                                                   |
| Docling               | `docling-project/docling`  | `bbdc862`                                  | MIT                           | Candidate remains unpromoted                                                                   |
| shadcn/ui             | `shadcn-ui/ui`             | `cb2bcd88d93b2f9bddb030e9136f1f8773e7eac4` | MIT                           | Source-adopted resizable primitive                                                             |
| Magic UI              | `magicuidesign/magicui`    | `0bd8b9fe0e15c4697c8d22dee1d35d88b5152c25` | MIT                           | Rejected for v4 truth surface                                                                  |
| React Bits            | `DavidHDev/react-bits`     | `d26ed7a`                                  | GitHub metadata `NOASSERTION` | Rejected pending published-license review                                                      |

The candidate registry remains authoritative for exact model repository
revisions. A newer code repository head does not silently replace a frozen
weight identity or measured runtime image.
