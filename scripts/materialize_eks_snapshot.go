// Executed from trusted Docs B, with the independently pinned Services module.
// The original Go validator must accept before any Content bytes are exported.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"

	"github.com/aisa-one/aisa-services/packages/apicontract"
)

func main() {
	if len(os.Args) != 3 {
		panic("input and fresh output required")
	}
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic("input unavailable")
	}
	if len(raw) > 65<<20 {
		panic("input exceeds bounds")
	}
	var snapshot apicontract.PublicationSnapshot
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&snapshot); err != nil {
		panic("invalid snapshot JSON")
	}
	var trailing any
	if err = decoder.Decode(&trailing); err != io.EOF {
		panic("trailing snapshot JSON")
	}
	if err = apicontract.ValidatePublicationSnapshot(snapshot); err != nil {
		panic("original Go snapshot validation failed")
	}
	sort.Slice(snapshot.Files, func(i, j int) bool { return snapshot.Files[i].Name < snapshot.Files[j].Name })
	out := os.Args[2]
	if err = os.Mkdir(out, 0700); err != nil {
		panic("fresh output required")
	}
	files := []map[string]string{}
	for _, file := range snapshot.Files {
		path := filepath.Join(out, file.Name)
		if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			panic("directory failed")
		}
		if err = os.WriteFile(path, file.Content, 0600); err != nil {
			panic("member write failed")
		}
		files = append(files, map[string]string{"name": file.Name, "media_type": file.MediaType, "sha256": file.SHA256})
	}
	meta := map[string]any{"schema_version": snapshot.SchemaVersion, "generation": snapshot.Generation,
		"source_digest": snapshot.SourceDigest, "compiler_revision": snapshot.CompilerRevision, "files": files}
	encoded, err := json.Marshal(meta)
	if err != nil {
		panic("metadata encoding failed")
	}
	if err = os.WriteFile(filepath.Join(out, "snapshot.json"), encoded, 0600); err != nil {
		panic("metadata write failed")
	}
	fmt.Println("Original Go PublicationSnapshot validation and materialization passed")
}
