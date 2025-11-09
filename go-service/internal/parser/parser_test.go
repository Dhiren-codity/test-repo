package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestParseFile(t *testing.T) {
	p := NewParser()

	content := `package main

import "fmt"

func main() {
	fmt.Println("Hello, World!")
}`

	file, err := p.ParseFile(content, "test.go")
	assert.NoError(t, err)
	assert.Equal(t, "go", file.Language)
	assert.Equal(t, "test.go", file.Path)
	assert.Greater(t, len(file.Lines), 0)
}

func TestAnalyzeDiff(t *testing.T) {
	p := NewParser()

	oldContent := `line1
line2
line3`

	newContent := `line1
line2_modified
line3
line4`

	diff, err := p.AnalyzeDiff(oldContent, newContent)
	assert.NoError(t, err)
	assert.Greater(t, len(diff.ModifiedLines), 0)
	assert.Greater(t, len(diff.AddedLines), 0)
}

func TestCalculateMetrics(t *testing.T) {
	p := NewParser()

	content := `package main

// This is a comment
import "fmt"

func main() {
	if true {
		fmt.Println("Hello")
	}
}`

	metrics := p.CalculateMetrics(content)
	assert.Greater(t, metrics.TotalLines, 0)
	assert.Greater(t, metrics.CodeLines, 0)
	assert.Greater(t, metrics.CommentLines, 0)
	assert.Greater(t, metrics.Functions, 0)
}

func TestDetectLanguage(t *testing.T) {
	testCases := []struct {
		path     string
		expected string
	}{
		{"test.go", "go"},
		{"test.py", "python"},
		{"test.rb", "ruby"},
		{"test.js", "javascript"},
		{"unknown.xyz", "unknown"},
	}

	for _, tc := range testCases {
		p := NewParser()
		file, _ := p.ParseFile("content", tc.path)
		assert.Equal(t, tc.expected, file.Language)
	}
}
