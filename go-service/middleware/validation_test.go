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
)

func TestValidateParseRequest_VariousScenarios(t *testing.T) {
	t.Run("empty content and traversal path", func(t *testing.T) {
		ClearValidationErrors()
		content := ""
		path := "../etc/passwd"
		errs := ValidateParseRequest(content, path)
		assert.Len(t, errs, 2)
		fields := []string{errs[0].Field, errs[1].Field}
		reasons := []string{errs[0].Reason, errs[1].Reason}
		assert.Contains(t, fields, "content")
		assert.Contains(t, fields, "path")
		assert.Contains(t, reasons, "Content is required and cannot be empty")
		assert.Contains(t, reasons, "Path contains potential directory traversal")

		logged := GetValidationErrors()
		assert.Len(t, logged, 2)
	})

	t.Run("content too large", func(t *testing.T) {
		ClearValidationErrors()
		content := strings.Repeat("a", MaxContentSize+1)
		path := "safe/path"
		errs := ValidateParseRequest(content, path)
		assert.Len(t, errs, 1)
		assert.Equal(t, "content", errs[0].Field)
		assert.Equal(t, "Content exceeds maximum size of 1MB", errs[0].Reason)

		logged := GetValidationErrors()
		assert.Len(t, logged, 1)
	})

	t.Run("content contains null bytes", func(t *testing.T) {
		ClearValidationErrors()
		content := "abc\x00def"
		path := "safe"
		errs := ValidateParseRequest(content, path)
		assert.Len(t, errs, 1)
		assert.Equal(t, "content", errs[0].Field)
		assert.Equal(t, "Content contains invalid null bytes", errs[0].Reason)
	})

	t.Run("path too long and traversal", func(t *testing.T) {
		ClearValidationErrors()
		path := strings.Repeat("a", MaxPathLength) + ".."
		content := "ok"
		errs := ValidateParseRequest(content, path)
		assert.Len(t, errs, 2)
		assert.Equal(t, "path", errs[0].Field)
		assert.Equal(t, "path", errs[1].Field)
		reasons := []string{errs[0].Reason, errs[1].Reason}
		assert.Contains(t, reasons, "Path exceeds maximum length")
		assert.Contains(t, reasons, "Path contains potential directory traversal")
	})
}

func TestValidateDiffRequest_RequiredAndSize(t *testing.T) {
	t.Run("both empty", func(t *testing.T) {
		ClearValidationErrors()
		errs := ValidateDiffRequest("", "")
		assert.Len(t, errs, 2)
		fields := []string{errs[0].Field, errs[1].Field}
		assert.Contains(t, fields, "old_content")
		assert.Contains(t, fields, "new_content")
	})

	t.Run("old too large", func(t *testing.T) {
		ClearValidationErrors()
		oldContent := strings.Repeat("a", MaxContentSize+1)
		newContent := "ok"
		errs := ValidateDiffRequest(oldContent, newContent)
		assert.Len(t, errs, 1)
		assert.Equal(t, "old_content", errs[0].Field)
		assert.Equal(t, "Old content exceeds maximum size", errs[0].Reason)
	})

	t.Run("new too large", func(t *testing.T) {
		ClearValidationErrors()
		oldContent := "ok"
		newContent := strings.Repeat("b", MaxContentSize+1)
		errs := ValidateDiffRequest(oldContent, newContent)
		assert.Len(t, errs, 1)
		assert.Equal(t, "new_content", errs[0].Field)
		assert.Equal(t, "New content exceeds maximum size", errs[0].Reason)
	})

	t.Run("both ok -> no errors and nothing logged", func(t *testing.T) {
		ClearValidationErrors()
		errs := ValidateDiffRequest("old", "new")
		assert.Len(t, errs, 0)
		logged := GetValidationErrors()
		assert.Len(t, logged, 0)
	})
}

func TestSanitizeInput_RemovesControlCharacters(t *testing.T) {
	raw := "hi" + string([]rune{0, 1, 7, 11, 12, 14, 31, 127, '\u0090'}) + " ok\n\t\rX"
	s := SanitizeInput(raw)
	assert.Equal(t, "hi ok\n\t\rX", s)
}

func TestSanitizeRequestBody_SanitizesJSONFields(t *testing.T) {
	body := map[string]any{
		"content":     "a\x00b\u0090c",
		"path":        "p\x00a\u0090th",
		"old_content": "old\x00\u0090",
		"new_content": "new\x00\u0090",
		"other":       "keep",
	}
	b, _ := json.Marshal(body)
	r := httptest.NewRequest(http.MethodPost, "/sanitize", bytes.NewBuffer(b))

	SanitizeRequestBody(r)

	// Read back
	dataBytes, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	var got map[string]any
	assert.NoError(t, json.Unmarshal(dataBytes, &got))

	assert.Equal(t, "abc", got["content"])
	assert.Equal(t, "path", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new", got["new_content"])
	assert.Equal(t, "keep", got["other"])

	assert.Equal(t, int64(len(dataBytes)), r.ContentLength)
}

func TestSanitizeRequestBody_PreservesNonJSON(t *testing.T) {
	raw := []byte("not json \x00")
	r := httptest.NewRequest(http.MethodPost, "/sanitize", bytes.NewBuffer(raw))

	SanitizeRequestBody(r)

	dataBytes, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	assert.Equal(t, raw, dataBytes)
}

func TestValidationMiddleware_SkipsForNonPOST(t *testing.T) {
	orig := []byte(`{"content":"a` + "\x00" + `b"}`)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})

	mw := ValidationMiddleware(next)
	req := httptest.NewRequest(http.MethodGet, "/x", bytes.NewBuffer(orig))
	rec := httptest.NewRecorder()

	mw.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, orig, rec.Body.Bytes())
}

func TestValidationMiddleware_SanitizesPostJSON(t *testing.T) {
	body := map[string]any{
		"content":     "A\x00B\u0090C",
		"path":        "P\x00Q",
		"old_content": "O\x00",
		"new_content": "N\u0090",
		"other":       "keep\x00", // not a targeted field; should remain unchanged in JSON
	}
	b, _ := json.Marshal(body)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Echo the body back
		data, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(data)
	})

	mw := ValidationMiddleware(next)
	req := httptest.NewRequest(http.MethodPost, "/x", bytes.NewBuffer(b))
	rec := httptest.NewRecorder()

	mw.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusOK, rec.Code)

	var got map[string]any
	assert.NoError(t, json.Unmarshal(rec.Body.Bytes(), &got))
	assert.Equal(t, "ABC", got["content"])
	assert.Equal(t, "PQ", got["path"])
	assert.Equal(t, "O", got["old_content"])
	assert.Equal(t, "N", got["new_content"])
	assert.Equal(t, "keep\x00", got["other"])
}

func TestValidationMiddleware_PassesThroughInvalidJSON(t *testing.T) {
	orig := []byte("not json \x00")

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})

	mw := ValidationMiddleware(next)
	req := httptest.NewRequest(http.MethodPost, "/x", bytes.NewBuffer(orig))
	rec := httptest.NewRecorder()

	mw.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, orig, rec.Body.Bytes())
}

func TestGetValidationErrors_ReturnsCopy(t *testing.T) {
	ClearValidationErrors()
	_ = ValidateParseRequest("", "safe") // logs at least one error
	got := GetValidationErrors()
	assert.NotEmpty(t, got)

	// mutate returned slice
	origField := got[0].Field
	got[0].Field = "changed"

	// ensure internal state not affected
	got2 := GetValidationErrors()
	assert.Equal(t, origField, got2[0].Field)
}

func TestClearValidationErrors_EmptiesStore(t *testing.T) {
	ClearValidationErrors()
	_ = ValidateParseRequest("", "path")
	assert.NotEmpty(t, GetValidationErrors())

	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestLogValidationErrors_TrimsToLast100(t *testing.T) {
	ClearValidationErrors()

	var errs []ValidationError
	for i := 0; i < 120; i++ {
		errs = append(errs, ValidationError{
			Field:  "f",
			Reason: "e" + strconvI(i),
			Time:   time.Now(),
		})
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	assert.Len(t, got, 100)
	assert.Equal(t, "e20", got[0].Reason)
	assert.Equal(t, "e119", got[len(got)-1].Reason)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

// helper: strconv.Itoa without importing strconv
func strconvI(i int) string {
	const digits = "0123456789"
	if i == 0 {
		return "0"
	}
	var buf [32]byte
	pos := len(buf)
	n := i
	for n > 0 {
		pos--
		buf[pos] = digits[n%10]
		n /= 10
	}
	return string(buf[pos:])
}
