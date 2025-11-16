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

func TestValidateParseRequest(t *testing.T) {
	ClearValidationErrors()

	tests := []struct {
		name        string
		content     string
		path        string
		wantFields  []string
		wantReasons []string
	}{
		{
			name:        "empty content",
			content:     "",
			path:        "",
			wantFields:  []string{"content"},
			wantReasons: []string{"Content is required and cannot be empty"},
		},
		{
			name:        "oversized content",
			content:     strings.Repeat("a", MaxContentSize+1),
			path:        "",
			wantFields:  []string{"content"},
			wantReasons: []string{"Content exceeds maximum size of 1MB"},
		},
		{
			name:        "content with null bytes",
			content:     "abc\x00def",
			path:        "",
			wantFields:  []string{"content"},
			wantReasons: []string{"Content contains invalid null bytes"},
		},
		{
			name:        "path too long",
			content:     "ok",
			path:        strings.Repeat("a", MaxPathLength+1),
			wantFields:  []string{"path"},
			wantReasons: []string{"Path exceeds maximum length"},
		},
		{
			name:        "path directory traversal",
			content:     "ok",
			path:        "../etc/passwd",
			wantFields:  []string{"path"},
			wantReasons: []string{"Path contains potential directory traversal"},
		},
		{
			name:        "valid content and path",
			content:     "ok",
			path:        "dir/file.txt",
			wantFields:  nil,
			wantReasons: nil,
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateParseRequest(tt.content, tt.path)
			if len(tt.wantFields) == 0 {
				assert.Empty(t, errs)
				return
			}
			assert.Equal(t, len(tt.wantFields), len(errs))
			for i, e := range errs {
				assert.Equal(t, tt.wantFields[i], e.Field)
				assert.Equal(t, tt.wantReasons[i], e.Reason)
				assert.WithinDuration(t, time.Now(), e.Time, time.Second*2)
			}
		})
	}
}

func TestValidateDiffRequest(t *testing.T) {
	ClearValidationErrors()

	tests := []struct {
		name        string
		oldContent  string
		newContent  string
		wantFields  []string
		wantReasons []string
	}{
		{
			name:        "both empty",
			oldContent:  "",
			newContent:  "",
			wantFields:  []string{"old_content", "new_content"},
			wantReasons: []string{"Old content is required", "New content is required"},
		},
		{
			name:        "old content oversized",
			oldContent:  strings.Repeat("x", MaxContentSize+1),
			newContent:  "ok",
			wantFields:  []string{"old_content"},
			wantReasons: []string{"Old content exceeds maximum size"},
		},
		{
			name:        "new content oversized",
			oldContent:  "ok",
			newContent:  strings.Repeat("x", MaxContentSize+1),
			wantFields:  []string{"new_content"},
			wantReasons: []string{"New content exceeds maximum size"},
		},
		{
			name:        "both valid",
			oldContent:  "old",
			newContent:  "new",
			wantFields:  nil,
			wantReasons: nil,
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			if len(tt.wantFields) == 0 {
				assert.Empty(t, errs)
				return
			}
			assert.Equal(t, len(tt.wantFields), len(errs))
			for i, e := range errs {
				assert.Equal(t, tt.wantFields[i], e.Field)
				assert.Equal(t, tt.wantReasons[i], e.Reason)
				assert.WithinDuration(t, time.Now(), e.Time, time.Second*2)
			}
		})
	}
}

func TestSanitizeInput_RemovesControlCharacters(t *testing.T) {
	in := "A\x00B" + string([]rune{1, 2, 7}) + "C\nD\tE\rF" + string([]rune{11, 12, 14}) + "G" + string([]rune{127}) + "H"
	out := SanitizeInput(in)
	assert.Equal(t, "ABC\nD\tE\rFGH", out)
}

func TestSanitizeRequestBody_JSON_SanitizesFields(t *testing.T) {
	bodyMap := map[string]interface{}{
		"content":     "Hello\x00World",
		"path":        "dir/..//file\x07.txt",
		"old_content": "Old\x01\n",
		"new_content": "New\x02\t",
		"other":       "keep_me",
	}
	raw, _ := json.Marshal(bodyMap)
	r := httptest.NewRequest(http.MethodPost, "/x", bytes.NewReader(raw))

	SanitizeRequestBody(r)

	// Read sanitized body
	sanitizedBytes, err := ioReadAllAndRestore(r)
	assert.NoError(t, err)

	var got map[string]interface{}
	err = json.Unmarshal(sanitizedBytes, &got)
	assert.NoError(t, err)

	assert.Equal(t, "HelloWorld", got["content"])
	assert.Equal(t, "dir/..//file.txt", got["path"])
	assert.Equal(t, "Old\n", got["old_content"])
	assert.Equal(t, "New\t", got["new_content"])
	assert.Equal(t, "keep_me", got["other"])

	assert.Equal(t, int64(len(sanitizedBytes)), r.ContentLength)
}

func TestSanitizeRequestBody_NonJSON_Preserved(t *testing.T) {
	orig := []byte("not-json\x00raw")
	r := httptest.NewRequest(http.MethodPost, "/x", bytes.NewReader(orig))

	SanitizeRequestBody(r)

	got, err := ioReadAllAndRestore(r)
	assert.NoError(t, err)
	assert.Equal(t, orig, got)
}

func TestValidationMiddleware_POST_SanitizesAndPasses(t *testing.T) {
	bodyMap := map[string]interface{}{
		"content":     "Hi\x00!",
		"path":        "a\x07/b",
		"old_content": "O\x01",
		"new_content": "N\x02",
	}
	raw, _ := json.Marshal(bodyMap)

	req := httptest.NewRequest(http.MethodPost, "/mw", bytes.NewReader(raw))
	rr := httptest.NewRecorder()

	var seen map[string]interface{}
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// read and decode what middleware passed
		bodyBytes, _ := ioReadAllAndRestore(r)
		_ = json.Unmarshal(bodyBytes, &seen)
		w.WriteHeader(http.StatusOK)
	})

	handler := ValidationMiddleware(next)
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, "Hi!", seen["content"])
	assert.Equal(t, "a/b", seen["path"])
	assert.Equal(t, "O", seen["old_content"])
	assert.Equal(t, "N", seen["new_content"])
}

func TestValidationMiddleware_POST_InvalidJSON_PassesOriginal(t *testing.T) {
	orig := []byte("this is not json\x00raw")
	req := httptest.NewRequest(http.MethodPost, "/mw", bytes.NewReader(orig))
	rr := httptest.NewRecorder()

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bodyBytes, _ := ioReadAllAndRestore(r)
		_, _ = w.Write(bodyBytes)
	})

	handler := ValidationMiddleware(next)
	handler.ServeHTTP(rr, req)

	assert.Equal(t, orig, rr.Body.Bytes())
}

func TestValidationMiddleware_NonPOST_PassThrough(t *testing.T) {
	orig := []byte("GET body\x00should remain")
	req := httptest.NewRequest(http.MethodGet, "/mw", bytes.NewReader(orig))
	rr := httptest.NewRecorder()

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bodyBytes, _ := ioReadAllAndRestore(r)
		_, _ = w.Write(bodyBytes)
	})

	handler := ValidationMiddleware(next)
	handler.ServeHTTP(rr, req)

	assert.Equal(t, orig, rr.Body.Bytes())
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	errs := ValidateParseRequest("", "")
	assert.Len(t, errs, 1)

	all := GetValidationErrors()
	assert.GreaterOrEqual(t, len(all), 1)
	found := false
	for _, e := range all {
		if e.Field == "content" && e.Reason == "Content is required and cannot be empty" {
			found = true
			break
		}
	}
	assert.True(t, found, "expected content required error to be logged")

	ClearValidationErrors()
	all = GetValidationErrors()
	assert.Empty(t, all)
}

func TestValidationErrors_Log_TrimsTo100(t *testing.T) {
	ClearValidationErrors()

	var times []time.Time
	for i := 0; i < 120; i++ {
		errs := ValidateParseRequest("", fmt.Sprintf("p%d", i))
		assert.Len(t, errs, 1)
		times = append(times, errs[0].Time)
	}

	got := GetValidationErrors()
	assert.Equal(t, 100, len(got))

	wantTimes := times[20:]
	for i := 0; i < 100; i++ {
		assert.Equal(t, "content", got[i].Field)
		assert.Equal(t, "Content is required and cannot be empty", got[i].Reason)
		assert.True(t, got[i].Time.Equal(wantTimes[i]), "index=%d got=%v want=%v", i, got[i].Time, wantTimes[i])
	}
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("abc\x00def"))
	assert.False(t, containsNullBytes("abcdef"))
}

// helper to read all from r.Body and restore it for potential further use
func ioReadAllAndRestore(r *http.Request) ([]byte, error) {
	b, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	r.Body.Close()
	r.Body = io.NopCloser(bytes.NewReader(b))
	return b, nil
}
