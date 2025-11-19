package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestValidateParseRequest_ContentCases(t *testing.T) {
	t.Cleanup(ClearValidationErrors)

	tests := []struct {
		name       string
		content    string
		path       string
		wantReason string
		wantField  string
	}{
		{
			name:       "empty content",
			content:    "",
			path:       "",
			wantField:  "content",
			wantReason: "Content is required",
		},
		{
			name:       "oversize content",
			content:    strings.Repeat("a", MaxContentSize+1),
			path:       "",
			wantField:  "content",
			wantReason: "Content exceeds maximum size of 1MB",
		},
		{
			name:       "content with null bytes",
			content:    "abc\x00def",
			path:       "",
			wantField:  "content",
			wantReason: "Content contains invalid null bytes",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()

			errs := ValidateParseRequest(tt.content, tt.path)
			require.Len(t, errs, 1)
			assert.Equal(t, tt.wantField, errs[0].Field)
			assert.Contains(t, errs[0].Reason, tt.wantReason)

			// Logged
			logged := GetValidationErrors()
			require.Len(t, logged, 1)
			assert.Equal(t, tt.wantField, logged[0].Field)
		})
	}
}

func TestValidateParseRequest_PathCases(t *testing.T) {
	t.Cleanup(ClearValidationErrors)

	// Exceeds max length
	longPath := strings.Repeat("p", MaxPathLength+1)
	errs := ValidateParseRequest("ok", longPath)
	require.Len(t, errs, 1)
	assert.Equal(t, "path", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "maximum length")

	// Directory traversal ".."
	errs = ValidateParseRequest("ok", "../etc/passwd")
	require.Len(t, errs, 1)
	assert.Equal(t, "path", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "directory traversal")

	// Directory traversal "~/"
	errs = ValidateParseRequest("ok", "~/secret")
	require.Len(t, errs, 1)
	assert.Equal(t, "path", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "directory traversal")

	// Both long and traversal -> two errors
	pathBoth := strings.Repeat("../", (MaxPathLength/3)+10)
	errs = ValidateParseRequest("ok", pathBoth)
	require.Len(t, errs, 2)
	reasons := []string{errs[0].Reason, errs[1].Reason}
	assert.Subset(t, reasons, []string{"Path exceeds maximum length", "Path contains potential directory traversal"})
}

func TestValidateDiffRequest_Cases(t *testing.T) {
	t.Cleanup(ClearValidationErrors)

	// Missing old
	errs := ValidateDiffRequest("", "new")
	require.Len(t, errs, 1)
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "required")

	// Missing new
	ClearValidationErrors()
	errs = ValidateDiffRequest("old", "")
	require.Len(t, errs, 1)
	assert.Equal(t, "new_content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "required")

	// Both oversize
	ClearValidationErrors()
	oversize := strings.Repeat("x", MaxContentSize+1)
	errs = ValidateDiffRequest(oversize, oversize)
	require.Len(t, errs, 2)
	fields := []string{errs[0].Field, errs[1].Field}
	assert.Subset(t, fields, []string{"old_content", "new_content"})
	assert.Contains(t, errs[0].Reason, "exceeds")
	assert.Contains(t, errs[1].Reason, "exceeds")

	// Logged
	logged := GetValidationErrors()
	assert.GreaterOrEqual(t, len(logged), 2)
}

func TestSanitizeInput_RemovesDisallowedControls(t *testing.T) {
	input := "Hi\x00there\x01!\nTab\tCarriage\rReturn\r\nDel\x7F"
	out := SanitizeInput(input)
	// Ensure preserved characters remain
	assert.Contains(t, out, "Hi")
	assert.Contains(t, out, "there")
	assert.Contains(t, out, "!\n")
	assert.Contains(t, out, "Tab\t")
	assert.Contains(t, out, "Carriage\rReturn\r\n")
	// Ensure removed controls are gone
	assert.NotContains(t, out, "\x00")
	assert.NotContains(t, out, "\x01")
	assert.NotContains(t, out, "\x7F")
}

func TestSanitizeRequestBody_SanitizesKnownFields(t *testing.T) {
	body := map[string]string{
		"content":     "a\x00b",
		"path":        "p\x01ath",
		"old_content": "o\x02ld",
		"new_content": "n\x7Few",
	}
	raw, _ := json.Marshal(body)
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(raw))

	SanitizeRequestBody(r)

	gotBytes, err := io.ReadAll(r.Body)
	require.NoError(t, err)

	var got map[string]string
	require.NoError(t, json.Unmarshal(gotBytes, &got))

	assert.Equal(t, "ab", got["content"])
	assert.Equal(t, "path", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new", got["new_content"])

	assert.Equal(t, int64(len(gotBytes)), r.ContentLength)
}

func TestSanitizeRequestBody_PassesThroughNonJSON(t *testing.T) {
	orig := []byte("not json \x00 here")
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(orig))

	SanitizeRequestBody(r)

	got, err := io.ReadAll(r.Body)
	require.NoError(t, err)
	assert.Equal(t, orig, got)
}

func TestValidationMiddleware_SanitizesPOSTBodyJSON(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotBytes, err := io.ReadAll(r.Body)
		require.NoError(t, err)

		var got map[string]string
		require.NoError(t, json.Unmarshal(gotBytes, &got))

		assert.Equal(t, "ab", got["content"])
		assert.Equal(t, "path", got["path"])
		assert.Equal(t, "old", got["old_content"])
		assert.Equal(t, "new", got["new_content"])

		assert.Equal(t, len(gotBytes), int(r.ContentLength))
		w.WriteHeader(http.StatusOK)
	})

	mw := ValidationMiddleware(handler)

	body := map[string]string{
		"content":     "a\x00b",
		"path":        "p\x01ath",
		"old_content": "o\x02ld",
		"new_content": "n\x7Few",
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/test", bytes.NewReader(raw))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Code)
}

func TestValidationMiddleware_NonPOST_PassThrough(t *testing.T) {
	orig := []byte("abc\x00def")
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got, err := io.ReadAll(r.Body)
		require.NoError(t, err)
		assert.Equal(t, orig, got)
		w.WriteHeader(http.StatusOK)
	})

	mw := ValidationMiddleware(handler)
	req := httptest.NewRequest(http.MethodGet, "/get", bytes.NewReader(orig))
	rr := httptest.NewRecorder()
	mw.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Code)
}

func TestGetAndClearValidationErrors_CopyAndReset(t *testing.T) {
	t.Cleanup(ClearValidationErrors)
	ClearValidationErrors()

	es := []ValidationError{
		{Field: "a", Reason: "ra"},
		{Field: "b", Reason: "rb"},
	}
	logValidationErrors(es)

	got := GetValidationErrors()
	require.Len(t, got, 2)
	// Modify returned slice should not affect internal store
	got = append(got, ValidationError{Field: "c", Reason: "rc"})
	require.Len(t, got, 3)

	got2 := GetValidationErrors()
	require.Len(t, got2, 2)

	ClearValidationErrors()
	require.Empty(t, GetValidationErrors())
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("abc\x00"))
	assert.False(t, containsNullBytes("abcdef"))
}

func TestLogValidationErrors_CapTo100(t *testing.T) {
	t.Cleanup(ClearValidationErrors)
	ClearValidationErrors()

	var es []ValidationError
	for i := 0; i < 120; i++ {
		es = append(es, ValidationError{Field: "f#" + strconvI(i), Reason: "r"})
	}
	logValidationErrors(es)

	got := GetValidationErrors()
	require.Len(t, got, 100)
	assert.Equal(t, "f#20", got[0].Field)
	assert.Equal(t, "f#119", got[len(got)-1].Field)
}

// strconvI is a tiny helper to avoid importing strconv for Atoi conversion in this test file.
func strconvI(i int) string {
	// simple int to string without strconv; limited use in test.
	const digits = "0123456789"
	if i == 0 {
		return "0"
	}
	neg := false
	if i < 0 {
		neg = true
		i = -i
	}
	var buf [20]byte
	pos := len(buf)
	for i > 0 {
		pos--
		buf[pos] = digits[i%10]
		i /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
