# Model Supply-Chain Incident

Triggers include upstream compromise, changed license, unsafe remote code,
malicious pickle/custom wheel, checksum drift, or an unapproved runtime image.

1. Set the affected model release to `quarantined` and route traffic to its
   pinned fallback recipe.
2. Block image/model promotion and preserve registry, license snapshot, SBOM,
   signature, scan, and benchmark artifacts.
3. Determine affected image digests, endpoints, jobs, tenants, and exports.
4. Rotate any build/runtime secret that the component could access.
5. Rebuild from an independently verified commit with network-denied import and
   sample inference. Do not reuse an untrusted cache or volume.
6. Repeat license/security review and the quality subset. Promote through
   1%→5%→20% canary or remain on the fallback.
7. Notify customers only through the approved incident process. Describe
   external model boundaries honestly.
