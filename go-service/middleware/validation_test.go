package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSanitizeInput_RemovesControlKeepsWhitespaceAndUnicode(t *testing.T) {
	input := "A\x00B\tC\nD\rE\x7F F\x01G\x02H 😀"
	got := SanitizeInput(input)
	assert.Equal(t, "AB\tC\nD\rE FGH 😀", got)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

func TestValidateParseRequest(t *testing.T) {
	tests := []struct {
		name           string
		content        string
		path           string
		wantErrs       int
		wantFields     []string
		wantReasonsSub []string
	}{
		{
			name:     "valid input",
			content:  "hello world",
			path:     "file.txt",
			wantErrs: 0,
		},
		{
			name:           "empty content",
			content:        "",
			path:           "file.txt",
			wantErrs:       1,
			wantFields:     []string{"content"},
			wantReasonsSub: []string{"Content is required"},
		},
		{
			name:           "content over size",
			content:        strings.Repeat("x", MaxContentSize+1),
			path:           "file.txt",
			wantErrs:       1,
			wantFields:     []string{"content"},
			wantReasonsSub: []string{"exceeds maximum size"},
		},
		{
			name:           "content contains null",
			content:        "abc\x00def",
			path:           "file.txt",
			wantErrs:       1,
			wantFields:     []string{"content"},
			wantReasonsSub: []string{"contains invalid null bytes"},
		},
		{
			name:           "path too long",
			content:        "ok",
			path:           strings.Repeat("a", MaxPathLength+1),
			wantErrs:       1,
			wantFields:     []string{"path"},
			wantReasonsSub: []string{"Path exceeds maximum length"},
		},
		{
			name:           "path traversal",
			content:        "ok",
			path:           "../etc/passwd",
			wantErrs:       1,
			wantFields:     []string{"path"},
			wantReasonsSub: []string{"directory traversal"},
		},
		{
			name:           "path length and traversal",
			content:        "ok",
			path:           strings.Repeat("a", MaxPathLength+1) + "../secret",
			wantErrs:       2,
			wantFields:     []string{"path", "path"},
			wantReasonsSub: []string{"maximum length", "directory traversal"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateParseRequest(tt.content, tt.path)
			assert.Len(t, errs, tt.wantErrs)
			for i, f := range tt.wantFields {
				assert.Equal(t, f, errs[i].Field)
				assert.Contains(t, errs[i].Reason, tt.wantReasonsSub[i])
			}

			stored := GetValidationErrors()
			assert.Len(t, stored, tt.wantErrs)
			// Clean up
			ClearValidationErrors()
		})
	}
}

func TestValidateDiffRequest(t *testing.T) {
	tests := []struct {
		name           string
		oldContent     string
		newContent     string
		wantErrs       int
		wantFields     []string
		wantReasonsSub []string
	}{
		{
			name:           "both empty",
			oldContent:     "",
			newContent:     "",
			wantErrs:       2,
			wantFields:     []string{"old_content", "new_content"},
			wantReasonsSub: []string{"required", "required"},
		},
		{
			name:           "old too long",
			oldContent:     strings.Repeat("o", MaxContentSize+1),
			newContent:     "ok",
			wantErrs:       1,
			wantFields:     []string{"old_content"},
			wantReasonsSub: []string{"exceeds maximum size"},
		},
		{
			name:           "new too long",
			oldContent:     "ok",
			newContent:     strings.Repeat("n", MaxContentSize+1),
			wantErrs:       1,
			wantFields:     []string{"new_content"},
			wantReasonsSub: []string{"exceeds maximum size"},
		},
		{
			name:       "valid",
			oldContent: "old",
			newContent: "new",
			wantErrs:   0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			assert.Len(t, errs, tt.wantErrs)
			for i, f := range tt.wantFields {
				assert.Equal(t, f, errs[i].Field)
				assert.Contains(t, errs[i].Reason, tt.wantReasonsSub[i])
			}
			stored := GetValidationErrors()
			assert.Len(t, stored, tt.wantErrs)
			ClearValidationErrors()
		})
	}
}

func TestSanitizeRequestBody_ValidJSON(t *testing.T) {
	body := map[string]any{
		"content":     "A\x00B\tC\nD\rE\x7F",
		"path":        "../weird\x00path",
		"old_content": "O\x00ld",
		"new_content": "N\x01ew",
		"other":       "unchanged", // will remain but sanitized not applied to unknown keys
	}
	raw, _ := json.Marshal(body)
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(raw))
	r.Header.Set("Content-Type", "application/json")

	SanitizeRequestBody(r)

	gotBytes, err := io.ReadAll(r.Body)
	require.NoError(t, err)
	assert.Equal(t, int64(len(gotBytes)), r.ContentLength)

	var got map[string]any
	require.NoError(t, json.Unmarshal(gotBytes, &got))

	// Assert sanitized fields
	assert.Equal(t, SanitizeInput(body["content"].(string)), got["content"])
	assert.Equal(t, SanitizeInput(body["path"].(string)), got["path"])
	assert.Equal(t, SanitizeInput(body["old_content"].(string)), got["old_content"])
	assert.Equal(t, SanitizeInput(body["new_content"].(string)), got["new_content"])
	assert.Equal(t, "unchanged", got["other"])
}

func TestSanitizeRequestBody_InvalidJSON(t *testing.T) {
	orig := []byte("{ invalid json")
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(orig))
	SanitizeRequestBody(r)
	got, err := io.ReadAll(r.Body)
	require.NoError(t, err)
	assert.Equal(t, orig, got)
}

func TestValidationMiddleware_POST_Sanitizes(t *testing.T) {
	mw := ValidationMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer r.Body.Close()
		b, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	}))

	payload := map[string]any{
		"content": "A\x00B",
		"path":    "~/bad",
	}
	raw, _ := json.Marshal(payload)

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/parse", bytes.NewReader(raw))
	mw.ServeHTTP(rr, req)

	res := rr.Result()
	defer res.Body.Close()
	body, _ := io.ReadAll(res.Body)

	var got map[string]any
	require.NoError(t, json.Unmarshal(body, &got))
	assert.Equal(t, SanitizeInput("A\x00B"), got["content"])
	assert.Equal(t, SanitizeInput("~/bad"), got["path"])
}

func TestValidationMiddleware_NonPOST_PassThrough(t *testing.T) {
	mw := ValidationMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer r.Body.Close()
		b, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	}))

	orig := []byte(`{"content":"A\x00B","path":"~/bad"}`)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/parse", bytes.NewReader(orig))
	mw.ServeHTTP(rr, req)

	res := rr.Result()
	defer res.Body.Close()
	body, _ := io.ReadAll(res.Body)
	assert.Equal(t, orig, body)
}

func TestGetAndClearValidationErrors_CopyAndClear(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	// Initially empty
	assert.Empty(t, GetValidationErrors())

	errs := []ValidationError{
		{Field: "content", Reason: "bad content", Time: time.Now()},
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	require.Len(t, got, 1)
	assert.Equal(t, "content", got[0].Field)
	assert.Equal(t, "bad content", got[0].Reason)

	// Modify returned slice should not affect internal store
	got[0].Reason = "modified"
	got2 := GetValidationErrors()
	require.Len(t, got2, 1)
	assert.Equal(t, "bad content", got2[0].Reason)

	// Clear should empty
	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestLogValidationErrors_BufferLimit(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	var errs []ValidationError
	for i := 0; i < 120; i++ {
		errs = append(errs, ValidationError{
			Field:  "f",
			Reason: "r" + strconvItoa(i),
			Time:   time.Now(),
		})
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	require.Len(t, got, 100)
	assert.Equal(t, "r20", got[0].Reason)
	assert.Equal(t, "r119", got[99].Reason)

	// Logging empty slice should not change
	logValidationErrors([]ValidationError{})
	got2 := GetValidationErrors()
	assert.Equal(t, got, got2)
}

func strconvItoa(i int) string {
	return strconvFormatInt(int64(i), 10)
}

// Minimal local helpers to avoid importing strconv directly in the import block
func strconvFormatInt(i int64, base int) string {
	const digits = "0123456789abcdefghijklmnopqrstuvwxyz"
	if base < 2 || base > len(digits) {
		base = 10
	}
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	var buf [65]byte
	pos := len(buf)
	for i > 0 {
		pos--
		buf[pos] = digits[i%int64(base)]
		i /= int64(base)
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
