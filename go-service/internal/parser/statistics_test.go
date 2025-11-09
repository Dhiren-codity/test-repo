package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func makeCodeFile(path string, size int, lines int, lang string) *CodeFile {
	return &CodeFile{
		Path:     path,
		Size:     size,
		Language: lang,
		Lines:    make([]string, lines),
	}
}

func TestNewStatisticsCalculator(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats_TableDriven(t *testing.T) {
	tests := []struct {
		name           string
		files          []*CodeFile
		wantTotalFiles int
		wantTotalLines int
		wantTotalSize  int
		wantAvgLines   float64
		wantAvgSize    float64
		wantLargest    string
		wantSmallest   string
		wantLangs      map[string]int
	}{
		{
			name:           "empty input",
			files:          []*CodeFile{},
			wantTotalFiles: 0,
			wantTotalLines: 0,
			wantTotalSize:  0,
			wantAvgLines:   0,
			wantAvgSize:    0,
			wantLargest:    "",
			wantSmallest:   "",
			wantLangs:      map[string]int{},
		},
		{
			name: "single file",
			files: []*CodeFile{
				makeCodeFile("a.go", 120, 3, "Go"),
			},
			wantTotalFiles: 1,
			wantTotalLines: 3,
			wantTotalSize:  120,
			wantAvgLines:   3.0,
			wantAvgSize:    120.0,
			wantLargest:    "a.go",
			wantSmallest:   "a.go",
			wantLangs:      map[string]int{"Go": 1},
		},
		{
			name: "multiple files",
			files: []*CodeFile{
				makeCodeFile("f1.go", 100, 10, "Go"),
				makeCodeFile("f2.py", 300, 20, "Python"),
				makeCodeFile("f3.go", 50, 5, "Go"),
			},
			wantTotalFiles: 3,
			wantTotalLines: 35,
			wantTotalSize:  450,
			wantAvgLines:   35.0 / 3.0,
			wantAvgSize:    150.0,
			wantLargest:    "f2.py",
			wantSmallest:   "f3.go",
			wantLangs:      map[string]int{"Go": 2, "Python": 1},
		},
	}

	sc := NewStatisticsCalculator()
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			stats := sc.CalculateFileStats(tt.files)
			assert.NotNil(t, stats)

			assert.Equal(t, tt.wantTotalFiles, stats.TotalFiles)
			assert.Equal(t, tt.wantTotalLines, stats.TotalLines)
			assert.Equal(t, tt.wantTotalSize, stats.TotalSize)
			assert.InDelta(t, tt.wantAvgLines, stats.AverageLines, 1e-9)
			assert.InDelta(t, tt.wantAvgSize, stats.AverageSize, 1e-9)
			assert.Equal(t, tt.wantLargest, stats.LargestFile)
			assert.Equal(t, tt.wantSmallest, stats.SmallestFile)

			assert.NotNil(t, stats.Languages)
			for lang, count := range tt.wantLangs {
				assert.Equal(t, count, stats.Languages[lang], "language count mismatch for %s", lang)
			}
			// Also ensure no unexpected extra languages in stats
			assert.Equal(t, len(tt.wantLangs), len(stats.Languages))
		})
	}
}

func TestStatisticsCalculator_CalculateFileStats_TieLargestKeepsFirst(t *testing.T) {
	files := []*CodeFile{
		makeCodeFile("first.go", 300, 10, "Go"),
		makeCodeFile("second.go", 300, 20, "Go"),
		makeCodeFile("third.go", 100, 5, "Go"),
	}
	sc := NewStatisticsCalculator()

	stats := sc.CalculateFileStats(files)
	assert.NotNil(t, stats)
	assert.Equal(t, "first.go", stats.LargestFile, "largest tie should keep the first occurrence")
}

func TestStatisticsCalculator_CalculateFileStats_TieSmallestKeepsFirst(t *testing.T) {
	files := []*CodeFile{
		makeCodeFile("first.go", 100, 10, "Go"),
		makeCodeFile("second.go", 100, 5, "Go"),
		makeCodeFile("third.go", 200, 15, "Go"),
	}
	sc := NewStatisticsCalculator()

	stats := sc.CalculateFileStats(files)
	assert.NotNil(t, stats)
	assert.Equal(t, "first.go", stats.SmallestFile, "smallest tie should keep the first occurrence")
}

func TestStatisticsCalculator_CalculateFileStats_NilReceiver(t *testing.T) {
	var sc *StatisticsCalculator // nil receiver
	files := []*CodeFile{
		makeCodeFile("a.go", 10, 2, "Go"),
		makeCodeFile("b.js", 20, 3, "JavaScript"),
	}
	// Method should still work since receiver isn't dereferenced
	stats := sc.CalculateFileStats(files)

	assert.NotNil(t, stats)
	assert.Equal(t, 2, stats.TotalFiles)
	assert.Equal(t, 5, stats.TotalLines)
	assert.Equal(t, 30, stats.TotalSize)
	assert.InDelta(t, 2.5, stats.AverageLines, 1e-9)
	assert.InDelta(t, 15.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "b.js", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
	assert.Equal(t, 1, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["JavaScript"])
}
