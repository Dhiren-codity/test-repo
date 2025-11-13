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

	"github.com/stretchr/testify/assert"
)

func TestValidateParseRequest(t *testing.T) {
	t.Run("table-driven parse validations and logging", func(t *testing.T) {
		type tc struct {
			name       string
			content    string
			path       string
			wantErrors []ValidationError
		}
		longContent := strings.Repeat("a", MaxContentSize+1)
		longPath := strings.Repeat("a", MaxPathLength+1)
		bothPathIssues := strings.Repeat("a", MaxPathLength-1) + ".." // results in length MaxPathLength+1 and contains ".."

		tests := []tc{
			{
				name:    "valid",
				content: "hello",
				path:    "folder/file.txt",
			},
			{
				name:    "empty content",
				content: "",
				path:    "file.txt",
				wantErrors: []ValidationError{
					{Field: "content", Reason: "Content is required and cannot be empty"},
				},
			},
			{
				name:    "content too large",
				content: longContent,
				path:    "file.txt",
				wantErrors: []ValidationError{
					{Field: "content", Reason: "Content exceeds maximum size of 1MB"},
				},
			},
			{
				name:    "content contains null bytes",
				content: "abc\x00def",
				path:    "file.txt",
				wantErrors: []ValidationError{
					{Field: "content", Reason: "Content contains invalid null bytes"},
				},
			},
			{
				name:    "path too long",
				content: "hello",
				path:    longPath,
				wantErrors: []ValidationError{
					{Field: "path", Reason: "Path exceeds maximum length"},
				},
			},
			{
				name:    "path traversal using ..",
				content: "hello",
				path:    "../etc/passwd",
				wantErrors: []ValidationError{
					{Field: "path", Reason: "Path contains potential directory traversal"},
				},
			},
			{
				name:    "path traversal using ~/",
				content: "hello",
				path:    "~/data",
				wantErrors: []ValidationError{
					{Field: "path", Reason: "Path contains potential directory traversal"},
				},
			},
			{
				name:    "path too long and traversal",
				content: "hello",
				path:    bothPathIssues,
				wantErrors: []ValidationError{
					{Field: "path", Reason: "Path exceeds maximum length"},
					{Field: "path", Reason: "Path contains potential directory traversal"},
				},
			},
		}

		for _, tt := range tests {
			t.Run(tt.name, func(t *testing.T) {
				ClearValidationErrors()
				errs := ValidateParseRequest(tt.content, tt.path)
				assert.Equal(t, len(tt.wantErrors), len(errs), "returned errors length")

				for i, we := range tt.wantErrors {
					assert.Equal(t, we.Field, errs[i].Field, "error field")
					assert.Equal(t, we.Reason, errs[i].Reason, "error reason")
					assert.False(t, errs[i].Time.IsZero(), "timestamp should be set")
				}

				// Verify logging captured identical errors count
				logged := GetValidationErrors()
				assert.Equal(t, len(tt.wantErrors), len(logged))
				ClearValidationErrors()
			})
		}
	})
}

func TestValidateDiffRequest(t *testing.T) {
	t.Run("table-driven diff validations and logging", func(t *testing.T) {
		type tc struct {
			name       string
			oldC       string
			newC       string
			wantErrors []ValidationError
		}
		long := strings.Repeat("x", MaxContentSize+1)
		tests := []tc{
			{
				name: "valid",
				oldC: "old content",
				newC: "new content",
			},
			{
				name: "old empty",
				oldC: "",
				newC: "new",
				wantErrors: []ValidationError{
					{Field: "old_content", Reason: "Old content is required"},
				},
			},
			{
				name: "new empty",
				oldC: "old",
				newC: "",
				wantErrors: []ValidationError{
					{Field: "new_content", Reason: "New content is required"},
				},
			},
			{
				name: "both too large",
				oldC: long,
				newC: long,
				wantErrors: []ValidationError{
					{Field: "old_content", Reason: "Old content exceeds maximum size"},
					{Field: "new_content", Reason: "New content exceeds maximum size"},
				},
			},
			{
				name: "old too large only",
				oldC: long,
				newC: "new-ok",
				wantErrors: []ValidationError{
					{Field: "old_content", Reason: "Old content exceeds maximum size"},
				},
			},
			{
				name: "new too large only",
				oldC: "old-ok",
				newC: long,
				wantErrors: []ValidationError{
					{Field: "new_content", Reason: "New content exceeds maximum size"},
				},
			},
		}
		for _, tt := range tests {
			t.Run(tt.name, func(t *testing.T) {
				ClearValidationErrors()
				errs := ValidateDiffRequest(tt.oldC, tt.newC)
				assert.Equal(t, len(tt.wantErrors), len(errs))
				for i, we := range tt.wantErrors {
					assert.Equal(t, we.Field, errs[i].Field)
					assert.Equal(t, we.Reason, errs[i].Reason)
					assert.False(t, errs[i].Time.IsZero())
				}
				logged := GetValidationErrors()
				assert.Equal(t, len(tt.wantErrors), len(logged))
				ClearValidationErrors()
			})
		}
	})
}

func TestSanitizeInput(t *testing.T) {
	// Control characters removal, keep \n \r \t
	in := "A\x00B\x01C\tD\nE\rF\x0bG\x0cH\x0eI\x7fJ\u200EK"
	out := SanitizeInput(in)
	assert.Equal(t, "ABC\tD\nE\rFGHIJK", out)

	// No-op case
	nochange := "Hello, 世界!\n\tOK"
	assert.Equal(t, nochange, SanitizeInput(nochange))
}

func TestSanitizeRequestBody_JSON(t *testing.T) {
	bodyMap := map[string]any{
		"content":     "A\x00B",
		"path":        "P\x0bQ",
		"old_content": "X\u200eY",
		"new_content": "N\x01M",
		"other":       123,
	}
	raw, _ := json.Marshal(bodyMap)
	r := httptest.NewRequest(http.MethodPost, "/x", bytes.NewBuffer(raw))

	SanitizeRequestBody(r)

	readBack, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	assert.Equal(t, int64(len(readBack)), r.ContentLength)

	var got map[string]any
	err = json.Unmarshal(readBack, &got)
	assert.NoError(t, err)

	assert.Equal(t, "AB", got["content"])
	assert.Equal(t, "PQ", got["path"])
	oc, ok := got["old_content"].(string)
	assert.True(t, ok)
	assert.Contains(t, []string{"XY", "X\u200eY"}, oc)
	assert.Equal(t, "NM", got["new_content"])
	// Ensure other non-target fields remain present
	_, ok = got["other"]
	assert.True(t, ok)
}

func TestSanitizeRequestBody_InvalidJSON(t *testing.T) {
	orig := []byte(`{"content":"A"`)
	r := httptest.NewRequest(http.MethodPost, "/x", bytes.NewBuffer(orig))

	SanitizeRequestBody(r)

	readBack, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	assert.Equal(t, string(orig), string(readBack))
}

func TestValidationMiddleware_SanitizesPost(t *testing.T) {
	unsanitized := map[string]any{
		"content":     "A\x00B",
		"path":        "P\x0bQ",
		"old_content": "X\u200eY",
		"new_content": "N\x01M",
	}
	raw, _ := json.Marshal(unsanitized)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		// ContentLength should match sanitized body len
		assert.Equal(t, int64(len(b)), r.ContentLength)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})
	mw := ValidationMiddleware(next)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/sanitize", bytes.NewBuffer(raw))
	mw.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	var got map[string]any
	err := json.Unmarshal(rec.Body.Bytes(), &got)
	assert.NoError(t, err)
	assert.Equal(t, "AB", got["content"])
	assert.Equal(t, "PQ", got["path"])
	oc, ok := got["old_content"].(string)
	assert.True(t, ok)
	assert.Contains(t, []string{"XY", "X\u200eY"}, oc)
	assert.Equal(t, "NM", got["new_content"])
}

func TestValidationMiddleware_SkipsNonPost(t *testing.T) {
	unsanitized := []byte(`{"content":"A` + "\x00" + `B"}`)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		// Middleware should not touch non-POST; ContentLength should be original len
		assert.Equal(t, int64(len(unsanitized)), r.ContentLength)
		assert.Equal(t, string(unsanitized), string(b))
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	mw := ValidationMiddleware(next)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/skip", bytes.NewBuffer(unsanitized))
	mw.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "ok", rec.Body.String())
}

func TestGetAndClearValidationErrors_CopyAndClear(t *testing.T) {
	ClearValidationErrors()
	logValidationErrors([]ValidationError{
		{Field: "f1", Reason: "r1"},
	})
	errs := GetValidationErrors()
	assert.Len(t, errs, 1)
	assert.Equal(t, "f1", errs[0].Field)
	// Mutate returned slice should not affect internal store
	errs[0].Field = "mutated"

	errs2 := GetValidationErrors()
	assert.Equal(t, "f1", errs2[0].Field)

	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestLogValidationErrors_TrimsTo100(t *testing.T) {
	ClearValidationErrors()
	var batch []ValidationError
	for i := 0; i < 105; i++ {
		batch = append(batch, ValidationError{
			Field:  fmt.Sprintf("f%d", i),
			Reason: fmt.Sprintf("r%d", i),
		})
	}
	logValidationErrors(batch)

	errs := GetValidationErrors()
	assert.Len(t, errs, 100)
	assert.Equal(t, "f5", errs[0].Field)
	assert.Equal(t, "f104", errs[99].Field)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("abc\x00def"))
	assert.False(t, containsNullBytes("abcdef"))
}
