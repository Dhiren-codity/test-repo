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
)

func TestValidateParseRequest_ContentValidationAndLogging(t *testing.T) {
	ClearValidationErrors()

	// Empty content
	errs := ValidateParseRequest("", "safe/path")
	assert.Len(t, errs, 1)
	assert.Equal(t, "content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "required")

	logged := GetValidationErrors()
	assert.Len(t, logged, 1)
	assert.Equal(t, errs[0].Field, logged[0].Field)
	assert.Contains(t, logged[0].Reason, "required")

	ClearValidationErrors()

	// Too large content
	large := strings.Repeat("a", MaxContentSize+1)
	errs = ValidateParseRequest(large, "safe/path")
	assert.Len(t, errs, 1)
	assert.Equal(t, "content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "exceeds")

	ClearValidationErrors()

	// Content with null bytes
	errs = ValidateParseRequest("abc\x00def", "safe/path")
	assert.Len(t, errs, 1)
	assert.Equal(t, "content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "null bytes")
}

func TestValidateParseRequest_PathValidation(t *testing.T) {
	ClearValidationErrors()

	// Path too long
	longPath := strings.Repeat("a", MaxPathLength+1)
	errs := ValidateParseRequest("ok", longPath)
	assert.Len(t, errs, 1)
	assert.Equal(t, "path", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "maximum length")

	ClearValidationErrors()

	// Path traversal
	errs = ValidateParseRequest("ok", "../etc/passwd")
	assert.Len(t, errs, 1)
	assert.Equal(t, "path", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "directory traversal")

	ClearValidationErrors()

	// Valid input
	errs = ValidateParseRequest("hello", "safe/subdir/file.txt")
	assert.Len(t, errs, 0)
}

func TestValidateDiffRequest_Basic(t *testing.T) {
	ClearValidationErrors()

	// Missing both
	errs := ValidateDiffRequest("", "")
	assert.Len(t, errs, 2)
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Equal(t, "new_content", errs[1].Field)
	assert.Contains(t, errs[0].Reason, "required")
	assert.Contains(t, errs[1].Reason, "required")

	ClearValidationErrors()

	// Old too large
	oldLarge := strings.Repeat("x", MaxContentSize+1)
	errs = ValidateDiffRequest(oldLarge, "new")
	assert.Len(t, errs, 1)
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "exceeds")

	ClearValidationErrors()

	// New too large
	newLarge := strings.Repeat("x", MaxContentSize+1)
	errs = ValidateDiffRequest("old", newLarge)
	assert.Len(t, errs, 1)
	assert.Equal(t, "new_content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "exceeds")

	ClearValidationErrors()

	// Valid both
	errs = ValidateDiffRequest("old", "new")
	assert.Len(t, errs, 0)
}

func TestSanitizeInput(t *testing.T) {
	in := "a\x00b\x01c\nd\te\rf\u007f"
	out := SanitizeInput(in)
	assert.Equal(t, "abc\nd\te\rf", out)

	// Control characters should be dropped except \n \r \t
	in2 := string([]rune{0, 1, 2, '\n', '\t', '\r', 'A'})
	out2 := SanitizeInput(in2)
	assert.Equal(t, "\n\t\rA", out2)

	// No change case
	in3 := "Hello, World!"
	assert.Equal(t, in3, SanitizeInput(in3))
}

func TestSanitizeRequestBody_JSON(t *testing.T) {
	body := `{
		"content": "a\x00b\x01c",
		"path": "x\u007fy",
		"old_content": "\x00",
		"new_content": "line1\x01\nline2"
	}`
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(body))

	SanitizeRequestBody(req)

	bs, err := io.ReadAll(req.Body)
	assert.NoError(t, err)

	var m map[string]string
	assert.NoError(t, json.Unmarshal(bs, &m))
	assert.Equal(t, "abc", m["content"])
	assert.Equal(t, "xy", m["path"])
	assert.Equal(t, "", m["old_content"])
	assert.Equal(t, "line1\nline2", m["new_content"])
}

func TestSanitizeRequestBody_InvalidJSON_Preserved(t *testing.T) {
	orig := "not-json"
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))

	SanitizeRequestBody(req)

	bs, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(bs))
}

func TestValidationMiddleware_SanitizesPostBody(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bs, _ := io.ReadAll(r.Body)
		// Pass through body so we can inspect response
		w.Header().Set("Content-Type", "application/json")
		w.Write(bs)
	})
	mw := ValidationMiddleware(next)

	reqBody := `{"content":"z\x00y\x01x","path":"a\u007fb","old_content":"\x00","new_content":"keep\nline\tand\rcarriage"}`
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(reqBody))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)

	var m map[string]string
	assert.NoError(t, json.Unmarshal(rr.Body.Bytes(), &m))
	assert.Equal(t, "zyx", m["content"])
	assert.Equal(t, "ab", m["path"])
	assert.Equal(t, "", m["old_content"])
	assert.Equal(t, "keep\nline\tand\rcarriage", m["new_content"])
}

func TestValidationMiddleware_NonPost_PassThrough(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bs, _ := io.ReadAll(r.Body)
		w.Write(bs)
	})
	mw := ValidationMiddleware(next)

	orig := `{"content":"a\x00b"}`
	req := httptest.NewRequest(http.MethodGet, "/", bytes.NewBufferString(orig))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, orig, rr.Body.String())
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())

	errs := []ValidationError{
		{Field: "f1", Reason: "r1"},
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	assert.Len(t, got, 1)
	assert.Equal(t, "f1", got[0].Field)
	assert.Equal(t, "r1", got[0].Reason)

	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestLogValidationErrors_TrimsTo100(t *testing.T) {
	ClearValidationErrors()

	var errs []ValidationError
	for i := 0; i < 150; i++ {
		errs = append(errs, ValidationError{
			Field:  "e#" + strconvI(i),
			Reason: "test",
		})
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	assert.Len(t, got, 100)
	assert.Equal(t, "e#50", got[0].Field)
	assert.Equal(t, "e#149", got[99].Field)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

// Helper to avoid importing strconv for a small conversion
func strconvI(i int) string {
	var buf [20]byte
	b := buf[:0]
	if i == 0 {
		return "0"
	}
	neg := false
	if i < 0 {
		neg = true
		i = -i
	}
	for i > 0 {
		d := i % 10
		b = append(b, byte('0'+d))
		i /= 10
	}
	if neg {
		b = append(b, '-')
	}
	// reverse
	for l, r := 0, len(b)-1; l < r; l, r = l+1, r-1 {
		b[l], b[r] = b[r], b[l]
	}
	return string(b)
}
