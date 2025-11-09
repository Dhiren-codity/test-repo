package parser

import (
	"bufio"
	"strings"
)

type CodeFile struct {
	Path     string
	Language string
	Lines    []string
	Size     int
}

type Diff struct {
	AddedLines    []int
	RemovedLines  []int
	ModifiedLines []int
}

type CodeMetrics struct {
	TotalLines   int
	CodeLines    int
	CommentLines int
	BlankLines   int
	Complexity   int
	Functions    int
	Classes      int
}

type Parser struct{}

func NewParser() *Parser {
	return &Parser{}
}

func (p *Parser) ParseFile(content string, path string) (*CodeFile, error) {
	lines := strings.Split(content, "\n")
	language := detectLanguage(path)

	return &CodeFile{
		Path:     path,
		Language: language,
		Lines:    lines,
		Size:     len(content),
	}, nil
}

func (p *Parser) AnalyzeDiff(oldContent, newContent string) (*Diff, error) {
	oldLines := strings.Split(oldContent, "\n")
	newLines := strings.Split(newContent, "\n")

	diff := &Diff{
		AddedLines:    []int{},
		RemovedLines:  []int{},
		ModifiedLines: []int{},
	}

	oldMap := make(map[int]string)
	for i, line := range oldLines {
		oldMap[i] = strings.TrimSpace(line)
	}

	newMap := make(map[int]string)
	for i, line := range newLines {
		newMap[i] = strings.TrimSpace(line)
	}

	maxLen := len(oldLines)
	if len(newLines) > maxLen {
		maxLen = len(newLines)
	}

	for i := 0; i < maxLen; i++ {
		oldLine := ""
		newLine := ""

		if i < len(oldLines) {
			oldLine = strings.TrimSpace(oldLines[i])
		}
		if i < len(newLines) {
			newLine = strings.TrimSpace(newLines[i])
		}

		if oldLine == "" && newLine != "" {
			diff.AddedLines = append(diff.AddedLines, i)
		} else if oldLine != "" && newLine == "" {
			diff.RemovedLines = append(diff.RemovedLines, i)
		} else if oldLine != "" && newLine != "" && oldLine != newLine {
			diff.ModifiedLines = append(diff.ModifiedLines, i)
		}
	}

	return diff, nil
}

func (p *Parser) CalculateMetrics(content string) *CodeMetrics {
	scanner := bufio.NewScanner(strings.NewReader(content))

	metrics := &CodeMetrics{}
	inComment := false
	inMultiLineComment := false

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		metrics.TotalLines++

		if line == "" {
			metrics.BlankLines++
			continue
		}

		if strings.HasPrefix(line, "//") || strings.HasPrefix(line, "#") || strings.HasPrefix(line, "--") {
			metrics.CommentLines++
			continue
		}

		if strings.Contains(line, "/*") {
			inMultiLineComment = true
		}
		if strings.Contains(line, "*/") {
			inMultiLineComment = false
			metrics.CommentLines++
			continue
		}

		if inMultiLineComment || inComment {
			metrics.CommentLines++
			continue
		}

		metrics.CodeLines++

		if strings.Contains(line, "func ") || strings.Contains(line, "def ") || strings.Contains(line, "function ") {
			metrics.Functions++
		}

		if strings.Contains(line, "class ") || strings.Contains(line, "type ") {
			metrics.Classes++
		}

		if strings.Contains(line, "if ") || strings.Contains(line, "for ") || strings.Contains(line, "while ") {
			metrics.Complexity++
		}
	}

	return metrics
}

func detectLanguage(path string) string {
	ext := strings.ToLower(path[strings.LastIndex(path, "."):])

	langMap := map[string]string{
		".go":   "go",
		".py":   "python",
		".rb":   "ruby",
		".js":   "javascript",
		".ts":   "typescript",
		".java": "java",
		".cpp":  "cpp",
		".c":    "c",
		".rs":   "rust",
	}

	if lang, ok := langMap[ext]; ok {
		return lang
	}

	return "unknown"
}
