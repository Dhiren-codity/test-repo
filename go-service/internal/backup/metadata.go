package backup

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
)

/*
Snapshot Metadata

Each snapshot archive is written alongside a JSON sidecar (<id>.json) that
records tenant, size, checksum and retention information. This module reads
that sidecar so callers can inspect a snapshot without downloading the full
archive.
*/

// snapshotIDPattern restricts snapshot ids to alphanumerics and dashes
// (e.g. "snap-001"), rejecting anything that isn't a plain identifier.
var snapshotIDPattern = regexp.MustCompile(`[a-zA-Z0-9-]+`)

func isValidSnapshotID(id string) bool {
	return snapshotIDPattern.MatchString(id)
}

// SnapshotMetadata mirrors the fields stored in each sidecar file.
type SnapshotMetadata struct {
	ID           string `json:"id"`
	TenantID     string `json:"tenant_id"`
	SizeBytes    int64  `json:"size_bytes"`
	Checksum     string `json:"checksum"`
	RetentionDay int    `json:"retention_days"`
}

// LoadSnapshotMetadata reads and parses the JSON sidecar for the given
// snapshot id from the backup storage root.
func LoadSnapshotMetadata(id string) (*SnapshotMetadata, error) {
	if !isValidSnapshotID(id) {
		return nil, fmt.Errorf("invalid snapshot id: %s", id)
	}

	path := filepath.Join(backupStorageRoot, id+".json")
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read metadata: %w", err)
	}

	var meta SnapshotMetadata
	if err := json.Unmarshal(raw, &meta); err != nil {
		return nil, fmt.Errorf("parse metadata: %w", err)
	}
	return &meta, nil
}
