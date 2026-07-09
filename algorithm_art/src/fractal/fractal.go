package main

import (
    "encoding/json"
    "flag"
    "fmt"
    "image"
    "image/color"
    "math"
    "math/rand"
    "os"
    "path/filepath"
    "time"

    "golang.org/x/image/bmp"
)

// ------------------------------------------------------------
// Defaults (match display)
// ------------------------------------------------------------

const (
	DefaultWidth  = 800
	DefaultHeight = 480

	MinVariance = 0.002
	MinGradient = 0.010
	MaxZoom     = 1e11
)

// ------------------------------------------------------------
// ACeP palette
// ------------------------------------------------------------

const (
	BLACK  = 0
	WHITE  = 1
	GREEN  = 2
	BLUE   = 3
	RED    = 4
	YELLOW = 5
	ORANGE = 6
)

type BGRA struct {
	B, G, R, A uint8
}

var acepPalette = []BGRA{
	{0, 0, 0, 0},
	{255, 255, 255, 0},
	{0, 255, 0, 0},
	{255, 0, 0, 0},
	{0, 0, 255, 0},
	{0, 255, 255, 0},
	{0, 165, 255, 0},
}

// ------------------------------------------------------------
// Persistent generator state
// ------------------------------------------------------------

type GeneratorState struct {
	CX    float64 `json:"cx"`
	CY    float64 `json:"cy"`
	Zoom  float64 `json:"zoom"`
	Frame int     `json:"frame"`
}

func loadState(path string) (*GeneratorState, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var s GeneratorState
	if err := json.Unmarshal(b, &s); err != nil {
		return nil, err
	}
	return &s, nil
}

func saveState(path string, s *GeneratorState) error {
	tmp := path + ".tmp"
	b, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(tmp, b, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// ------------------------------------------------------------
// Starting-point selection
//
// A uniformly random (cx, cy) in the complex plane almost always lands
// either deep inside a solid black interior region or far out in the
// featureless exterior — both render as a flat, boring frame and can
// trip the MinVariance/MinGradient "structure exhausted" exit below.
// Instead we pick among a curated list of well-known boundary-region
// coordinates (each independently verified to clear the variance/
// gradient thresholds at zoom=100) and jitter within a fraction of the
// current field of view, so every seed still lands somewhere with real
// detail while still varying frame to frame.
// ------------------------------------------------------------

type StartPoint struct {
	CX, CY, Zoom float64
}

var startPoints = []StartPoint{
	{-0.743643887037158, 0.131825904205311, 100}, // seahorse valley
	{-0.7746806106269039, 0.1374168856037867, 100}, // mini-mandelbrot
	{-0.101097, 0.95629, 100},                      // elephant valley
	{0.42884, -0.231345, 100},                      // spiral A
	{-1.25066, 0.02012, 100},                       // seahorse valley 2
	{-0.235125, 0.827215, 100},                     // triple spiral
	{-1.7497587, 0.00002262, 100},                  // valley near -1.75
	{-0.5557506, 0.5405568, 100},                   // julia island
	{-0.748, 0.1, 100},                             // classic tendril
	{-0.16070135, 1.0375665, 100},                  // double spiral
}

// jitterFraction is how far (as a fraction of the field-of-view width at
// the chosen zoom) the starting point may be nudged. Verified empirically
// to stay well clear of the quality thresholds up to ~15%; kept smaller
// here for margin.
const jitterFraction = 0.10

func randomStartPoint(rng *rand.Rand) *GeneratorState {
	p := startPoints[rng.Intn(len(startPoints))]
	fov := 4.0 / p.Zoom // field-of-view width in complex-plane units
	jitter := fov * jitterFraction
	return &GeneratorState{
		CX:   p.CX + (rng.Float64()*2-1)*jitter,
		CY:   p.CY + (rng.Float64()*2-1)*jitter,
		Zoom: p.Zoom,
	}
}

// ------------------------------------------------------------
// Mandelbrot render (faithful port)
// ------------------------------------------------------------

func render(
	out []uint8,
	width, height int,
	state *GeneratorState,
	maxIter int,
	fg, bg uint8,
) (variance, gradient float64) {

	n := width * height
	nu := make([]float64, n)

	scale := 4.0 / (float64(width) * state.Zoom)
	x0 := state.CX - float64(width)*0.5*scale
	y0 := state.CY - float64(height)*0.5*scale

	var mean, mean2 float64

	for y := 0; y < height; y++ {
		ci := y0 + float64(y)*scale
		for x := 0; x < width; x++ {
			cr := x0 + float64(x)*scale
			zr, zi := 0.0, 0.0
			zr2, zi2 := 0.0, 0.0
			iter := 0

			for zr2+zi2 < 16.0 && iter < maxIter {
				zi = 2*zr*zi + ci
				zr = zr2 - zi2 + cr
				zr2 = zr * zr
				zi2 = zi * zi
				iter++
			}

			v := 0.0
			if iter < maxIter {
				v = float64(iter) + 1.0 -
					math.Log2(math.Log(math.Sqrt(zr2+zi2)))
			}

			i := y*width + x
			nu[i] = v
			mean += v
			mean2 += v * v
		}
	}

	mean /= float64(n)
	mean2 /= float64(n)
	variance = mean2 - mean*mean

	for y := 1; y < height-1; y++ {
		for x := 1; x < width-1; x++ {
			i := y*width + x
			dx := nu[i+1] - nu[i-1]
			dy := nu[i+width] - nu[i-width]
			gradient += math.Hypot(dx, dy)
		}
	}
	gradient /= float64(n)

	for i := 0; i < n; i++ {
		if nu[i] > mean {
			out[i] = fg
		} else {
			out[i] = bg
		}
	}

	return
}

// ------------------------------------------------------------
// BMP writer (8-bit indexed, atomic)
func writeBMPAtomic(path string, pixels []uint8, width, height int) error {
    tmp := path + ".tmp"

    img := image.NewRGBA(image.Rect(0, 0, width, height))

    for y := 0; y < height; y++ {
        for x := 0; x < width; x++ {
            idx := pixels[y*width+x]

            if int(idx) >= len(acepPalette) {
                idx = BLACK
            }

            p := acepPalette[idx]

            img.SetRGBA(x, y, color.RGBA{
                R: p.R,
                G: p.G,
                B: p.B,
                A: 255,
            })
        }
    }

    f, err := os.Create(tmp)
    if err != nil {
        return err
    }

    if err := bmp.Encode(f, img); err != nil {
        f.Close()
        return err
    }

    if err := f.Close(); err != nil {
        return err
    }

    return os.Rename(tmp, path)
}
// ------------------------------------------------------------
// Main
// ------------------------------------------------------------

func main() {
	width := flag.Int("width", DefaultWidth, "image width")
	height := flag.Int("height", DefaultHeight, "image height")
	outDir := flag.String("out", "out", "output directory")
	frames := flag.Int("frames", 1, "number of frames (ignored with --single)")
	single := flag.Bool("single", false, "generate exactly one frame")
	statePath := flag.String("state", "", "state JSON file")

	fgName := flag.String("fg", "white", "foreground color")
	bgName := flag.String("bg", "black", "background color")
	seed := flag.Int64("seed", 0, "random seed for choosing a fresh starting point "+
		"(0 = derive one from the current time); only affects renders that "+
		"start a new sequence — has no effect once a --state file exists")
	flag.Parse()

	colorMap := map[string]uint8{
		"black": BLACK, "white": WHITE, "green": GREEN,
		"blue": BLUE, "red": RED, "yellow": YELLOW, "orange": ORANGE,
	}

	fg, ok1 := colorMap[*fgName]
	bg, ok2 := colorMap[*bgName]
	if !ok1 || !ok2 {
		fmt.Println("Invalid color name")
		os.Exit(1)
	}

	os.MkdirAll(*outDir, 0755)

	effectiveSeed := *seed
	if effectiveSeed == 0 {
		effectiveSeed = time.Now().UnixNano()
	}
	rng := rand.New(rand.NewSource(effectiveSeed))

	// Load or initialize state
	var state *GeneratorState
	if *statePath != "" {
		if s, err := loadState(*statePath); err == nil {
			state = s
		}
	}
	if state == nil {
		state = randomStartPoint(rng)
		fmt.Printf("New sequence: seed=%d cx=%g cy=%g zoom=%g\n",
			effectiveSeed, state.CX, state.CY, state.Zoom)
	}

	frameBuf := make([]uint8, (*width)*(*height))
	count := *frames
	if *single {
		count = 1
	}

	for i := 0; i < count; i++ {
		if state.Zoom > MaxZoom {
			os.Exit(10)
		}

		maxIter := int(math.Min(
			4096,
			math.Max(
				256,
				256+math.Pow(math.Log10(state.Zoom), 1.6)*120,
			),
		))

		variance, gradient := render(
			frameBuf, *width, *height, state, maxIter, fg, bg,
		)

		fmt.Printf(
			"Frame %d zoom=%g var=%g grad=%g\n",
			state.Frame, state.Zoom, variance, gradient,
		)

		if variance < MinVariance || gradient < MinGradient {
			fmt.Println("Structure exhausted — stopping")
			os.Exit(10)
		}

		outFile := filepath.Join(*outDir, "current.bmp")
		if err := writeBMPAtomic(outFile, frameBuf, *width, *height); err != nil {
			fmt.Fprintln(os.Stderr, "write error:", err)
			os.Exit(20)
		}

		state.Zoom *= 1.25
		state.Frame++

		if *statePath != "" {
			saveState(*statePath, state)
		}
	}
}
