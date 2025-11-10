package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func newCodeFile(path string, size int, lang string, nLines int) *CodeFile {
	lines := make([]string, nLines)
	for i := 0; i < nLines; i++ {
		lines[i] = "line"
	}
	return &CodeFile{
		Path:     path,
		Size:     size,
		Language: lang,
		Lines:    lines,
	}
}

func TestNewStatisticsCalculator(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats(t *testing.T) {
	tests := []struct {
		name           string
		files          []*CodeFile
		wantTotalFiles int
		wantTotalLines int
		wantTotalSize  int
		wantAvgLines   float64
		wantAvgSize    float64
		wantLanguages  map[string]int
		wantLargest    string
		wantSmallest   string
	}{
		{
			name:           "empty slice",
			files:          nil,
			wantTotalFiles: 0,
			wantTotalLines: 0,
			wantTotalSize:  0,
			wantAvgLines:   0.0,
			wantAvgSize:    0.0,
			wantLanguages:  map[string]int{},
			wantLargest:    "",
			wantSmallest:   "",
		},
		{
			name:           "single file",
			files:          []*CodeFile{newCodeFile("a.go", 120, "Go", 3)},
			wantTotalFiles: 1,
			wantTotalLines: 3,
			wantTotalSize:  120,
			wantAvgLines:   3.0,
			wantAvgSize:    120.0,
			wantLanguages:  map[string]int{"Go": 1},
			wantLargest:    "a.go",
			wantSmallest:   "a.go",
		},
		{
			name: "multiple files different languages",
			files: []*CodeFile{
				newCodeFile("a.py", 50, "Python", 2),
				newCodeFile("b.go", 200, "Go", 4),
				newCodeFile("c.py", 100, "Python", 10),
			},
			wantTotalFiles: 3,
			wantTotalLines: 16,  // 2 + 4 + 10
			wantTotalSize:  350, // 50 + 200 + 100
			wantAvgLines:   16.0 / 3.0,
			wantAvgSize:    350.0 / 3.0,
			wantLanguages:  map[string]int{"Python": 2, "Go": 1},
			wantLargest:    "b.go",
			wantSmallest:   "a.py",
		},
		{
			name: "all same size tie for largest and smallest",
			files: []*CodeFile{
				newCodeFile("first.go", 100, "Go", 1),
				newCodeFile("second.go", 100, "Go", 2),
				newCodeFile("third.rs", 100, "Rust", 3),
			},
			wantTotalFiles: 3,
			wantTotalLines: 6,
			wantTotalSize:  300,
			wantAvgLines:   2.0,
			wantAvgSize:    100.0,
			wantLanguages:  map[string]int{"Go": 2, "Rust": 1},
			wantLargest:    "first.go", // ties retain the first file path
			wantSmallest:   "first.go", // ties retain the first file path
		},
		{
			name: "tie for largest picks first encountered max",
			files: []*CodeFile{
				newCodeFile("a.txt", 10, "Text", 1),
				newCodeFile("b.txt", 500, "Text", 2),
				newCodeFile("c.txt", 500, "Text", 3),
			},
			wantTotalFiles: 3,
			wantTotalLines: 6,
			wantTotalSize:  1010,
			wantAvgLines:   2.0,
			wantAvgSize:    336.6666666667,
			wantLanguages:  map[string]int{"Text": 3},
			wantLargest:    "b.txt",
			wantSmallest:   "a.txt",
		},
		{
			name: "tie for smallest picks first encountered min",
			files: []*CodeFile{
				newCodeFile("x.bin", 100, "Bin", 1),
				newCodeFile("y.bin", 10, "Bin", 2),
				newCodeFile("z.bin", 10, "Bin", 3),
			},
			wantTotalFiles: 3,
			wantTotalLines: 6,
			wantTotalSize:  120,
			wantAvgLines:   2.0,
			wantAvgSize:    40.0,
			wantLanguages:  map[string]int{"Bin": 3},
			wantLargest:    "x.bin",
			wantSmallest:   "y.bin",
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

			assert.NotNil(t, stats.Languages)
			assert.Equal(t, tt.wantLanguages, stats.Languages)

			assert.Equal(t, tt.wantLargest, stats.LargestFile)
			assert.Equal(t, tt.wantSmallest, stats.SmallestFile)
		})
	}
}
