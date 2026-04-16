# Third-Party Notices

`SentinelFlow` is released under the MIT License.

This file documents third-party open source components used in this project and the obligations arising from their licenses.

---

## 1. Runtime Dependencies

This project depends on third-party packages at runtime. Key dependency manifests:

- Python dependencies: `runtime/requirements.txt`
- Frontend dependencies: `webui/package.json`

Each dependency is governed by its own license. Please refer to the respective package's license file or registry entry for details.

---

## 2. Incorporated or Adapted Third-Party Code

### flocks

Portions of the frontend UI in this project are based on or adapted from **flocks**,
which is licensed under the Apache License, Version 2.0.

```
Copyright The flocks Authors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

The full text of the Apache License, Version 2.0 is available at:
https://www.apache.org/licenses/LICENSE-2.0

---

## 3. Pre-Release Checklist

Before any public release, ensure the following:

1. This file accurately lists all incorporated third-party components
2. The root `LICENSE` file is consistent with the project's stated license
3. Copyright and attribution notices for Apache 2.0 components are preserved as required by §4(c) of that license
4. Dependency license summaries are generated if needed (e.g., via `pip-licenses` or `license-checker`)
