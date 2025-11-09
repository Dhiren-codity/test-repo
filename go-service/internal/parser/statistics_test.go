package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func linesOf(n int) []string {
	lines := make([]string, n)
	for i := 0; i < n; i++ {
		lines[i] = "x"
	}
	return lines
}

func TestNewStatisticsCalculator_ReturnsNonNil(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()

	stats := sc.CalculateFileStats(nil)
	assert.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 0, len(stats.Languages))
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)

	stats2 := sc.CalculateFileStats([]*CodeFile{})
	assert.NotNil(t, stats2)
	assert.Equal(t, 0, stats2.TotalFiles)
	assert.Equal(t, 0, stats2.TotalLines)
	assert.Equal(t, 0, stats2.TotalSize)
	assert.NotNil(t, stats2.Languages)
	assert.Equal(t, 0, len(stats2.Languages))
	assert.Equal(t, "", stats2.LargestFile)
	assert.Equal(t, "", stats2.SmallestFile)
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "main.go",
			Size:     123,
			Lines:    linesOf(10),
			Language: "Go",
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 10, stats.TotalLines)
	assert.Equal(t, 123, stats.TotalSize)
	assert.InDelta(t, 10.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 123.0, stats.AverageSize, 1e-9)

	assert.Equal(t, "main.go", stats.LargestFile)
	assert.Equal(t, "main.go", stats.SmallestFile)

	assert.Equal(t, 1, len(stats.Languages))
	assert.Equal(t, 1, stats.Languages["Go"])
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFiles(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     100,
			Lines:    linesOf(10),
			Language: "Go",
		},
		{
			Path:     "b.py",
			Size:     50,
			Lines:    linesOf(5),
			Language: "Python",
		},
		{
			Path:     "c.js",
			Size:     200,
			Lines:    linesOf(20),
			Language: "JavaScript",
		},
		{
			Path:     "d.py",
			Size:     150,
			Lines:    linesOf(15),
			Language: "Python",
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 4, stats.TotalFiles)
	assert.Equal(t, 50, stats.TotalLines)
	assert.Equal(t, 500, stats.TotalSize)
	assert.InDelta(t, 12.5, stats.AverageLines, 1e-9)
	assert.InDelta(t, 125.0, stats.AverageSize, 1e-9)

	assert.Equal(t, "c.js", stats.LargestFile)
	assert.Equal(t, "b.py", stats.SmallestFile)

	assert.Equal(t, 3, len(stats.Languages))
	assert.Equal(t, 1, stats.Languages["Go"])
	assert.Equal(t, 2, stats.Languages["Python"])
	assert.Equal(t, 1, stats.Languages["JavaScript"])
}

func TestStatisticsCalculator_CalculateFileStats_TiesKeepFirst(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.txt",
			Size:     100,
			Lines:    linesOf(1),
			Language: "Text",
		},
		{
			Path:     "b.txt",
			Size:     100,
			Lines:    linesOf(2),
			Language: "Text",
		},
		{
			Path:     "c.txt",
			Size:     100,
			Lines:    linesOf(3),
			Language: "Text",
		},
	}

	stats := sc.CalculateFileStats(files)

	// With equal sizes, LargestFile and SmallestFile should remain the first file encountered
	assert.Equal(t, "a.txt", stats.LargestFile)
	assert.Equal(t, "a.txt", stats.SmallestFile)
}

func TestStatisticsCalculator_NilReceiver_Works(t *testing.T) {
	var sc *StatisticsCalculator // nil receiver
	files := []*CodeFile{
		{
			Path:     "x",
			Size:     10,
			Lines:    linesOf(2),
			Language: "X",
		},
		{
			Path:     "y",
			Size:     20,
			Lines:    linesOf(3),
			Language: "Y",
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 2, stats.TotalFiles)
	assert.Equal(t, 5, stats.TotalLines)
	assert.Equal(t, 30, stats.TotalSize)
	assert.InDelta(t, 2.5, stats.AverageLines, 1e-9)
	assert.InDelta(t, 15.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "y", stats.LargestFile)
	assert.Equal(t, "x", stats.SmallestFile)
	assert.Equal(t, 1, stats.Languages["X"])
	assert.Equal(t, 1, stats.Languages["Y"])
}
