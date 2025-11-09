package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func makeLines(n int) []string {
	lines := make([]string, n)
	for i := 0; i < n; i++ {
		lines[i] = "line"
	}
	return lines
}

func TestNewStatisticsCalculator_ReturnsNonNil(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()

	var files []*CodeFile
	stats := sc.CalculateFileStats(files)

	assert.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 0, len(stats.Languages))
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     100,
			Language: "Go",
			Lines:    makeLines(5),
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.NotNil(t, stats)
	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 5, stats.TotalLines)
	assert.Equal(t, 100, stats.TotalSize)
	assert.InDelta(t, 5.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
	assert.Equal(t, 1, stats.Languages["Go"])
	assert.Equal(t, 1, len(stats.Languages))
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFiles(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     100,
			Language: "Go",
			Lines:    makeLines(5),
		},
		{
			Path:     "b.py",
			Size:     50,
			Language: "Python",
			Lines:    makeLines(10),
		},
		{
			Path:     "c.js",
			Size:     150,
			Language: "JavaScript",
			Lines:    makeLines(1),
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.NotNil(t, stats)
	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 16, stats.TotalLines) // 5 + 10 + 1
	assert.Equal(t, 300, stats.TotalSize) // 100 + 50 + 150
	assert.InDelta(t, float64(16)/3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, float64(300)/3.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "c.js", stats.LargestFile)
	assert.Equal(t, "b.py", stats.SmallestFile)

	assert.Equal(t, 1, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])
	assert.Equal(t, 1, stats.Languages["JavaScript"])
	assert.Equal(t, 3, len(stats.Languages))
}

func TestStatisticsCalculator_CalculateFileStats_SizeTiesKeepFirst(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "first.txt",
			Size:     100,
			Language: "Text",
			Lines:    makeLines(2),
		},
		{
			Path:     "second.txt",
			Size:     100, // tie with max and min
			Language: "Text",
			Lines:    makeLines(3),
		},
		{
			Path:     "third.txt",
			Size:     100, // tie again
			Language: "Text",
			Lines:    makeLines(4),
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.NotNil(t, stats)
	assert.Equal(t, "first.txt", stats.LargestFile)
	assert.Equal(t, "first.txt", stats.SmallestFile)
	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 9, stats.TotalLines) // 2 + 3 + 4
	assert.Equal(t, 300, stats.TotalSize)
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)
	assert.Equal(t, 3, stats.Languages["Text"])
}
