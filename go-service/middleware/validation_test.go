package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestValidateParseRequest_ContentValidationAndLogging(t *testing.T) {
	ClearValidationErrors()

	// Empty content
	errs := ValidateParseRequest("", "safe/path")
	if len(errs) != 1 {
		t.Fatalf("expected 1 error, got %d: %+v", len(errs), errs)
	}
	if errs[0].Field != "content" {
		t.Fatalf("expected field 'content', got %q", errs[0].Field)
	}
	if !strings.Contains(errs[0].Reason, "required") {
		t.Fatalf("expected reason to contain 'required', got %q", errs[0].Reason)
	}

	logged := GetValidationErrors()
	if len(logged) != 1 {
		t.Fatalf("expected 1 logged error, got %d: %+v", len(logged), logged)
	}
	if logged[0].Field != errs[0].Field {
		t.Fatalf("expected logged field %q, got %q", errs[0].Field, logged[0].Field)
	}
	if !strings.Contains(logged[0].Reason, "required") {
		t.Fatalf("expected logged reason to contain 'required', got %q", logged[0].Reason)
	}

	ClearValidationErrors()

	// Too large content
	large := strings.Repeat("a", MaxContentSize+1)
	errs = ValidateParseRequest(large, "safe/path")
	if len(errs) != 1 {
		t.Fatalf("expected 1 error, got %d: %+v", len(errs), errs)
	}
	if errs[0].Field != "content" {
		t.Fatalf("expected field 'content', got %q", errs[0].Field)
	}
	if !strings.Contains(errs[0].Reason, "exceeds") {
		t.Fatalf("expected reason to contain 'exceeds', got %q", errs[0].Reason)
	}

	ClearValidationErrors()

	// Content with null bytes
	errs = ValidateParseRequest("abc\x00def", "safe/path")
	if len(errs) != 1 {
		t.Fatalf("expected 1 error, got %d: %+v", len(errs), errs)
	}
	if errs[0].Field != "content" {
		t.Fatalf("expected field 'content', got %q", errs[0].Field)
	}
	if !strings.Contains(errs[0].Reason, "null bytes") {
		t.Fatalf("expected reason to contain 'null bytes', got %q", errs[0].Reason)
	}
}

func TestValidateParseRequest_PathValidation(t *testing.T) {
	ClearValidationErrors()

	// Path too long
	longPath := strings.Repeat("a", MaxPathLength+1)
	errs := ValidateParseRequest("ok", longPath)
	if len(errs) != 1 {
		t.Fatalf("expected 1 error, got %d: %+v", len(errs), errs)
	}
	if errs[0].Field != "path" {
		t.Fatalf("expected field 'path', got %q", errs[0].Field)
	}
	if !strings.Contains(errs[0].Reason, "maximum length") {
		t.Fatalf("expected reason to contain 'maximum length', got %q", errs[0].Reason)
	}

	ClearValidationErrors()

	// Path traversal
	errs = ValidateParseRequest("ok", "../etc/passwd")
	if len(errs) != 1 {
		t.Fatalf("expected 1 error, got %d: %+v", len(errs), errs)
	}
	if errs[0].Field != "path" {
		t.Fatalf("expected field 'path', got %q", errs[0].Field)
	}
	if !strings.Contains(errs[0].Reason, "directory traversal") {
		t.Fatalf("expected reason to contain 'directory traversal', got %q", errs[0].Reason)
	}

	ClearValidationErrors()

	// Valid input
	errs = ValidateParseRequest("hello", "safe/subdir/file.txt")
	if len(errs) != 0 {
		t.Fatalf("expected 0 errors, got %d: %+v", len(errs), errs)
	}
}

func TestValidateDiffRequest_Basic(t *testing.T) {
	ClearValidationErrors()

	// Missing both
	errs := ValidateDiffRequest("", "")
	if len(errs) != 2 {
		t.Fatalf("expected 2 errors, got %d: %+v", len(errs), errs)
	}
	if errs[0].Field != "old_content" || errs[1].Field != "new_content" {
		t.Fatalf("expected fields 'old_content' and 'new_content', got %q and %q", errs[0].Field, errs[1].Field)
	}
	if !strings.Contains(errs[0].Reason, "required") || !strings.Contains(errs[1].Reason, "required") {
		t.Fatalf("expected both reasons to contain 'required', got %q and %q", errs[0].Reason, errs[1].Reason)
	}

	ClearValidationErrors()

	// Old too large
	oldLarge := strings.Repeat("x", MaxContentSize+1)
	errs = ValidateDiffRequest(oldLarge, "new")
	if len(errs) != 1 {
		t.Fatalf("expected 1 error, got %d: %+v", len(errs), errs)
	}
	if errs[0].Field != "old_content" {
		t.Fatalf("expected field 'old_content', got %q", errs[0].Field)
	}
	if !strings.Contains(errs[0].Reason, "exceeds") {
		t.Fatalf("expected reason to contain 'exceeds', got %q", errs[0].Reason)
	}

	ClearValidationErrors()

	// New too large
	newLarge := strings.Repeat("x", MaxContentSize+1)
	errs = ValidateDiffRequest("old", newLarge)
	if len(errs) != 1 {
		t.Fatalf("expected 1 error, got %d: %+v", len(errs), errs)
	}
	if errs[0].Field != "new_content" {
		t.Fatalf("expected field 'new_content', got %q", errs[0].Field)
	}
	if !strings.Contains(errs[0].Reason, "exceeds") {
		t.Fatalf("expected reason to contain 'exceeds', got %q", errs[0].Reason)
	}

	ClearValidationErrors()

	// Valid both
	errs = ValidateDiffRequest("old", "new")
	if len(errs) != 0 {
		t.Fatalf("expected 0 errors, got %d: %+v", len(errs), errs)
	}
}

func TestSanitizeInput(t *testing.T) {
	in := "a\x00b\x01c\nd\te\rf\u007f"
	out := SanitizeInput(in)
	if out != "abc\nd\te\rf" {
		t.Fatalf("expected %q, got %q", "abc\nd\te\rf", out)
	}

	// Control characters should be dropped except \n \r \t
	in2 := string([]rune{0, 1, 2, '\n', '\t', '\r', 'A'})
	out2 := SanitizeInput(in2)
	if out2 != "\n\t\rA" {
		t.Fatalf("expected %q, got %q", "\n\t\rA", out2)
	}

	// No change case
	in3 := "Hello, World!"
	if SanitizeInput(in3) != in3 {
		t.Fatalf("expected %q to remain unchanged", in3)
	}
}

func TestSanitizeRequestBody_JSON(t *testing.T) {
	body := `{
		"content": "a\u0000b\u0001c",
		"path": "x\u007fy",
		"old_content": "\u0000",
		"new_content": "line1\u0001\nline2"
	}`
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(body))

	SanitizeRequestBody(req)

	bs, err := io.ReadAll(req.Body)
	if err != nil {
		t.Fatalf("unexpected error reading body: %v", err)
	}

	var m map[string]string
	if err := json.Unmarshal(bs, &m); err != nil {
		t.Fatalf("unexpected json unmarshal error: %v", err)
	}
	if m["content"] != "abc" {
		t.Fatalf("expected content %q, got %q", "abc", m["content"])
	}
	if m["path"] != "xy" {
		t.Fatalf("expected path %q, got %q", "xy", m["path"])
	}
	if m["old_content"] != "" {
		t.Fatalf("expected old_content %q, got %q", "", m["old_content"])
	}
	if m["new_content"] != "line1\nline2" {
		t.Fatalf("expected new_content %q, got %q", "line1\nline2", m["new_content"])
	}
}

func TestSanitizeRequestBody_InvalidJSON_Preserved(t *testing.T) {
	orig := "not-json"
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))

	SanitizeRequestBody(req)

	bs, err := io.ReadAll(req.Body)
	if err != nil {
		t.Fatalf("unexpected error reading body: %v", err)
	}
	if string(bs) != orig {
		t.Fatalf("expected body %q, got %q", orig, string(bs))
	}
}

func TestValidationMiddleware_SanitizesPostBody(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bs, _ := io.ReadAll(r.Body)
		// Pass through body so we can inspect response
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(bs)
	})
	mw := ValidationMiddleware(next)

	reqBody := `{"content":"z\u0000y\u0001x","path":"a\u007fb","old_content":"\u0000","new_content":"keep\nline\tand\rcarriage"}`
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(reqBody))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d", http.StatusOK, rr.Code)
	}

	var m map[string]string
	if err := json.Unmarshal(rr.Body.Bytes(), &m); err != nil {
		t.Fatalf("unexpected json unmarshal error: %v", err)
	}
	if m["content"] != "zyx" {
		t.Fatalf("expected content %q, got %q", "zyx", m["content"])
	}
	if m["path"] != "ab" {
		t.Fatalf("expected path %q, got %q", "ab", m["path"])
	}
	if m["old_content"] != "" {
		t.Fatalf("expected old_content %q, got %q", "", m["old_content"])
	}
	if m["new_content"] != "keep\nline\tand\rcarriage" {
		t.Fatalf("expected new_content %q, got %q", "keep\nline\tand\rcarriage", m["new_content"])
	}
}

func TestValidationMiddleware_NonPost_PassThrough(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bs, _ := io.ReadAll(r.Body)
		_, _ = w.Write(bs)
	})
	mw := ValidationMiddleware(next)

	orig := `{"content":"a\u0000b"}`
	req := httptest.NewRequest(http.MethodGet, "/", bytes.NewBufferString(orig))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d", http.StatusOK, rr.Code)
	}
	if rr.Body.String() != orig {
		t.Fatalf("expected body %q, got %q", orig, rr.Body.String())
	}
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	if len(GetValidationErrors()) != 0 {
		t.Fatalf("expected no validation errors")
	}

	errs := []ValidationError{
		{Field: "f1", Reason: "r1"},
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	if len(got) != 1 {
		t.Fatalf("expected 1 validation error, got %d", len(got))
	}
	if got[0].Field != "f1" {
		t.Fatalf("expected field %q, got %q", "f1", got[0].Field)
	}
	if got[0].Reason != "r1" {
		t.Fatalf("expected reason %q, got %q", "r1", got[0].Reason)
	}

	ClearValidationErrors()
	if len(GetValidationErrors()) != 0 {
		t.Fatalf("expected no validation errors after clear")
	}
}

func TestLogValidationErrors_TrimsTo100(t *testing.T) {
	ClearValidationErrors()

	var errs []ValidationError
	for i := 0; i < 150; i++ {
		errs = append(errs, ValidationError{
			Field:  "e#" + helperItoa(i),
			Reason: "test",
		})
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	if len(got) != 100 {
		t.Fatalf("expected 100 validation errors, got %d", len(got))
	}
	if got[0].Field != "e#50" {
		t.Fatalf("expected first field %q, got %q", "e#50", got[0].Field)
	}
	if got[99].Field != "e#149" {
		t.Fatalf("expected last field %q, got %q", "e#149", got[99].Field)
	}
}

func TestContainsNullBytes(t *testing.T) {
	if !containsNullBytes("a\x00b") {
		t.Fatalf("expected containsNullBytes to return true")
	}
	if containsNullBytes("abc") {
		t.Fatalf("expected containsNullBytes to return false")
	}
}

// Helper to avoid importing strconv for a small conversion
func helperItoa(i int) string {
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
