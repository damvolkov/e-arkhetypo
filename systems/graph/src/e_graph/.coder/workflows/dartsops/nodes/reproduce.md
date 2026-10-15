# reproduce — actor: coder

Run the readout again and check each intake signal still speaks:

```
make dartsops-eval PIPELINE=<pipeline> EXPECTS="<expectations>"
```

A signal that does not reproduce (transient model drift, a flaky tier) is noted and dropped; if nothing
reproduces, return `{green: true, reason: "signals did not reproduce"}` and the loop closes honestly.

Return `{reproduced: [signal…], dropped: [signal…]}`.
