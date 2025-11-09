package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func makeCodeFile(path, lang string, size int, lineCount int) *CodeFile {
	lines := make([]string, lineCount)
	for i := 0; i < lineCount; i++ {
		lines[i] = "line"
	}
	return &CodeFile{
		Path:     path,
		Language: lang,
		Size:     size,
		Lines:    lines,
	}
}

func TestNewStatisticsCalculator_ReturnsInstance(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats_EmptySlice(t *testing.T) {
	sc := NewStatisticsCalculator()
	stats := sc.CalculateFileStats(nil)

	assert.NotNil(t, stats)
	assert.NotNil(t, stats.Languages)

	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Equal(t, 0, len(stats.Languages))
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		makeCodeFile("a.go", "Go", 100, 10),
	}

	stats := sc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 10, stats.TotalLines)
	assert.Equal(t, 100, stats.TotalSize)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)

	assert.Len(t, stats.Languages, 1)
	assert.Equal(t, 1, stats.Languages["Go"])

	assert.InDelta(t, 10.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFilesMixedLanguages(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		makeCodeFile("a.go", "Go", 10, 1),
		makeCodeFile("b.py", "Python", 30, 3),
		makeCodeFile("c.go", "Go", 20, 2),
	}

	stats := sc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 6, stats.TotalLines) // 1 + 3 + 2
	assert.Equal(t, 60, stats.TotalSize) // 10 + 30 + 20

	assert.Equal(t, "b.py", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)

	// Language counts
	assert.Len(t, stats.Languages, 2)
	assert.Equal(t, 2, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])

	// Averages
	assert.InDelta(t, 2.0, stats.AverageLines, 1e-9) // 6/3
	assert.InDelta(t, 20.0, stats.AverageSize, 1e-9) // 60/3
}

func TestStatisticsCalculator_CalculateFileStats_TiesKeepFirstOccurrence(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		makeCodeFile("first.txt", "txt", 100, 1),
		makeCodeFile("second.txt", "txt", 100, 2),
		makeCodeFile("third.txt", "txt", 100, 3),
	}

	stats := sc.CalculateFileStats(files)

	// Since comparisons use > and <, equal sizes should not update largest/smallest
	assert.Equal(t, "first.txt", stats.LargestFile)
	assert.Equal(t, "first.txt", stats.SmallestFile)
}

func TestStatisticsCalculator_CalculateFileStats_AverageIsFloatDivision(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		makeCodeFile("f1", "X", 1, 1),
		makeCodeFile("f2", "Y", 2, 2),
	}

	stats := sc.CalculateFileStats(files)

	assert.InDelta(t, 1.5, stats.AverageLines, 1e-9)
	assert.InDelta(t, 1.5, stats.AverageSize, 1e-9)
}

func TestStatisticsCalculator_CalculateFileStats_IndependenceAcrossCalls(t *testing.T) {
	sc := NewStatisticsCalculator()

	files1 := []*CodeFile{
		makeCodeFile("a.go", "Go", 10, 1),
	}
	files2 := []*CodeFile{
		makeCodeFile("b.py", "Python", 20, 2),
	}

	stats1 := sc.CalculateFileStats(files1)
	stats2 := sc.CalculateFileStats(files2)

	// First call
	assert.Equal(t, 1, stats1.TotalFiles)
	assert.Equal(t, 1, stats1.TotalLines)
	assert.Equal(t, 10, stats1.TotalSize)
	assert.Equal(t, "a.go", stats1.LargestFile)
	assert.Equal(t, "a.go", stats1.SmallestFile)
	assert.Equal(t, 1, stats1.Languages["Go"])
	assert.Equal(t, 0, stats1.Languages["Python"])

	// Second call
	assert.Equal(t, 1, stats2.TotalFiles)
	assert.Equal(t, 2, stats2.TotalLines)
	assert.Equal(t, 20, stats2.TotalSize)
	assert.Equal(t, "b.py", stats2.LargestFile)
	assert.Equal(t, "b.py", stats2.SmallestFile)
	assert.Equal(t, 1, stats2.Languages["Python"])
	assert.Equal(t, 0, stats2.Languages["Go"])
}
