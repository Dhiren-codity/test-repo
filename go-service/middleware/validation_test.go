package middleware

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestValidateParseRequest_VariousErrorsAndLogging(t *testing.T) {
	tests := []struct {
		name       string
		content    string
		path       string
		wantErrs   []ValidationError
		globalLogs int
	}{
		{
			name:    "empty content",
			content: "",
			path:    "valid/path.txt",
			wantErrs: []ValidationError{
				{Field: "content", Reason: "Content is required and cannot be empty"},
			},
			globalLogs: 1,
		},
		{
			name:    "content exceeds size",
			content: strings.Repeat("a", MaxContentSize+1),
			path:    "valid/path.txt",
			wantErrs: []ValidationError{
				{Field: "content", Reason: "Content exceeds maximum size of 1MB"},
			},
			globalLogs: 1,
		},
		{
			name:    "content contains null byte",
			content: "hello\x00world",
			path:    "valid/path.txt",
			wantErrs: []ValidationError{
				{Field: "content", Reason: "Content contains invalid null bytes"},
			},
			globalLogs: 1,
		},
		{
			name:    "path exceeds length",
			content: "ok",
			path:    strings.Repeat("p", MaxPathLength+1),
			wantErrs: []ValidationError{
				{Field: "path", Reason: "Path exceeds maximum length"},
			},
			globalLogs: 1,
		},
		{
			name:    "path traversal detected",
			content: "ok",
			path:    "../etc/passwd",
			wantErrs: []ValidationError{
				{Field: "path", Reason: "Path contains potential directory traversal"},
			},
			globalLogs: 1,
		},
		{
			name:    "path both long and traversal",
			content: "ok",
			path:    strings.Repeat("a", MaxPathLength+1) + "../",
			wantErrs: []ValidationError{
				{Field: "path", Reason: "Path exceeds maximum length"},
				{Field: "path", Reason: "Path contains potential directory traversal"},
			},
			globalLogs: 2,
		},
		{
			name:       "no errors",
			content:    "valid content",
			path:       "safe/path.txt",
			wantErrs:   nil,
			globalLogs: 0,
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			t.Cleanup(ClearValidationErrors)

			errs := ValidateParseRequest(tt.content, tt.path)
			if len(tt.wantErrs) == 0 {
				assert.Empty(t, errs)
				assert.Empty(t, GetValidationErrors())
				return
			}
			assert.Len(t, errs, len(tt.wantErrs))
			for i, we := range tt.wantErrs {
				assert.Equal(t, we.Field, errs[i].Field)
				assert.Equal(t, we.Reason, errs[i].Reason)
				assert.WithinDuration(t, time.Now(), errs[i].Time, time.Second)
			}
			glob := GetValidationErrors()
			assert.Len(t, glob, tt.globalLogs)
		})
	}
}

func TestValidateDiffRequest_VariousCases(t *testing.T) {
	tests := []struct {
		name     string
		oldC     string
		newC     string
		wantErrs []ValidationError
	}{
		{
			name: "both empty",
			oldC: "",
			newC: "",
			wantErrs: []ValidationError{
				{Field: "old_content", Reason: "Old content is required"},
				{Field: "new_content", Reason: "New content is required"},
			},
		},
		{
			name: "old empty new set",
			oldC: "",
			newC: "new",
			wantErrs: []ValidationError{
				{Field: "old_content", Reason: "Old content is required"},
			},
		},
		{
			name: "old exceeds size",
			oldC: strings.Repeat("o", MaxContentSize+1),
			newC: "ok",
			wantErrs: []ValidationError{
				{Field: "old_content", Reason: "Old content exceeds maximum size"},
			},
		},
		{
			name: "new exceeds size",
			oldC: "ok",
			newC: strings.Repeat("n", MaxContentSize+1),
			wantErrs: []ValidationError{
				{Field: "new_content", Reason: "New content exceeds maximum size"},
			},
		},
		{
			name:     "both valid",
			oldC:     "old",
			newC:     "new",
			wantErrs: nil,
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			t.Cleanup(ClearValidationErrors)

			errs := ValidateDiffRequest(tt.oldC, tt.newC)
			if len(tt.wantErrs) == 0 {
				assert.Empty(t, errs)
				assert.Empty(t, GetValidationErrors())
				return
			}
			assert.Len(t, errs, len(tt.wantErrs))
			for i, we := range tt.wantErrs {
				assert.Equal(t, we.Field, errs[i].Field)
				assert.Equal(t, we.Reason, errs[i].Reason)
				assert.WithinDuration(t, time.Now(), errs[i].Time, time.Second)
			}
			glob := GetValidationErrors()
			assert.Len(t, glob, len(tt.wantErrs))
		})
	}
}

func TestSanitizeInput_RemovesDisallowedControls(t *testing.T) {
	input := "a" + string(rune(0)) + string(rune(1)) + "\n" + "\t" + "\r" + string(rune(31)) + string(rune(127)) + "b"
	got := SanitizeInput(input)
	assert.Equal(t, "a\n\t\rb", got)

	// Additional controls: 0x0B, 0x0C, 0x0E
	input2 := "x" + string(rune(11)) + string(rune(12)) + string(rune(14)) + "y"
	got2 := SanitizeInput(input2)
	assert.Equal(t, "xy", got2)
}

func TestSanitizeRequestBody_JSON_SanitizesFieldsAndResetsBody(t *testing.T) {
	body := map[string]any{
		"content":     "a\x00b\n",
		"path":        "p\x7fath",
		"old_content": "o\x01ld",
		"new_content": "n\x1few\t",
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(raw))

	SanitizeRequestBody(req)

	// Read back the sanitized body and confirm values
	bs, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	// ContentLength should match the sanitized body length
	assert.Equal(t, int64(len(bs)), req.ContentLength)

	var got map[string]any
	err = json.Unmarshal(bs, &got)
	assert.NoError(t, err)

	assert.Equal(t, "ab\n", got["content"])
	assert.Equal(t, "path", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new\t", got["new_content"])
}

func TestSanitizeRequestBody_NonJSON_RestoresOriginal(t *testing.T) {
	orig := []byte("not json")
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(orig))
	SanitizeRequestBody(req)
	bs, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, bs)
	// ContentLength should remain as originally set by NewRequest
	assert.Equal(t, int64(len(orig)), req.ContentLength)
}

func TestValidationMiddleware_POST_SanitizesAndPassesDown(t *testing.T) {
	payload := map[string]any{
		"content":     "a\x00b",
		"path":        "p\x7fath",
		"old_content": "o\x01ld",
		"new_content": "n\x1few",
	}
	raw, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/parse", bytes.NewReader(raw))
	rr := httptest.NewRecorder()

	var received []byte
	var receivedCL int64
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var err error
		received, err = io.ReadAll(r.Body)
		assert.NoError(t, err)
		receivedCL = r.ContentLength
		w.WriteHeader(http.StatusOK)
	})
	h := ValidationMiddleware(next)
	h.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Code)

	var got map[string]any
	err := json.Unmarshal(received, &got)
	assert.NoError(t, err)
	assert.Equal(t, "ab", got["content"])
	assert.Equal(t, "path", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new", got["new_content"])
	assert.Equal(t, int64(len(received)), receivedCL)
}

func TestValidationMiddleware_NonPOST_PassesThroughUnchanged(t *testing.T) {
	payload := map[string]any{
		"content": "a\x00b",
	}
	raw, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodGet, "/parse", bytes.NewReader(raw))
	rr := httptest.NewRecorder()

	var received []byte
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var err error
		received, err = io.ReadAll(r.Body)
		assert.NoError(t, err)
		w.WriteHeader(http.StatusOK)
	})
	h := ValidationMiddleware(next)
	h.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Code)

	// Should be unchanged (no sanitization on non-POST)
	assert.Equal(t, raw, received)
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	t.Cleanup(ClearValidationErrors)

	assert.Empty(t, GetValidationErrors())

	now := time.Now()
	logValidationErrors([]ValidationError{
		{Field: "f1", Reason: "r1", Time: now},
		{Field: "f2", Reason: "r2", Time: now},
	})
	errs := GetValidationErrors()
	assert.Len(t, errs, 2)
	assert.Equal(t, "f1", errs[0].Field)
	assert.Equal(t, "f2", errs[1].Field)

	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

func TestLogValidationErrors_KeepsLast100(t *testing.T) {
	ClearValidationErrors()
	t.Cleanup(ClearValidationErrors)

	for i := 0; i < 110; i++ {
		logValidationErrors([]ValidationError{
			{Field: fmt.Sprintf("f%d", i), Reason: "r", Time: time.Now()},
		})
	}
	errs := GetValidationErrors()
	assert.Len(t, errs, 100)
	assert.Equal(t, "f10", errs[0].Field)
	assert.Equal(t, "f109", errs[len(errs)-1].Field)
}
