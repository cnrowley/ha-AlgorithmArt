package main

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// ============================================================
// Configuration
// ============================================================

const (
	W         = 800
	H         = 480
	TotalPix  = int64(W) * int64(H)
	WalkersPF = 1200
	MaxSteps  = 6000
	ThickRad  = 1

	// SpawnMargin is how far outside the layer's current cluster radius new
	// walkers are launched, in pixels.
	//
	// Previously walkers spawned uniformly across the entire 800x480
	// canvas. Since the cluster starts as a single pixel, almost every
	// walker started hundreds of pixels away — and a random walk needs
	// roughly distance^2 steps to have a real chance of reaching a target,
	// so with MaxSteps=6000 anything beyond ~100px essentially never
	// sticks. The handful of walkers that got lucky early gave their
	// layer a slightly larger capture area, compounding over frames while
	// the other layers stayed frozen at one pixel — a rich-get-richer
	// effect that looked like "only two layers are growing." Launching
	// from a ring just outside the cluster's current radius keeps the
	// distance-to-target roughly constant regardless of cluster size, so
	// every layer grows at a comparable, predictable rate.
	SpawnMargin = 30.0
)

// ============================================================
// Color + BMP
// ============================================================

type Color uint8

const (
	WHITE Color = iota
	BLACK
	BLUE
	GREEN
	RED
	YELLOW
)

type RGB struct {
	r, g, b uint8
}

func toRGB(c Color) RGB {
	switch c {
	case BLACK:
		return RGB{0, 0, 0}
	case BLUE:
		return RGB{0, 0, 255}
	case GREEN:
		return RGB{0, 200, 0}
	case RED:
		return RGB{200, 0, 0}
	case YELLOW:
		return RGB{200, 200, 0}
	default:
		return RGB{255, 255, 255}
	}
}

func writeBMP24(path string, pix []Color) error {
	rowBytes := (3*W + 3) &^ 3
	dataSize := rowBytes * H
	fileSize := 54 + dataSize

	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	header := make([]byte, 54)
	header[0] = 'B'
	header[1] = 'M'
	binary.LittleEndian.PutUint32(header[2:], uint32(fileSize))
	binary.LittleEndian.PutUint32(header[10:], 54)
	binary.LittleEndian.PutUint32(header[14:], 40)
	binary.LittleEndian.PutUint32(header[18:], uint32(W))
	binary.LittleEndian.PutUint32(header[22:], uint32(H))
	binary.LittleEndian.PutUint16(header[26:], 1)
	binary.LittleEndian.PutUint16(header[28:], 24)
	binary.LittleEndian.PutUint32(header[34:], uint32(dataSize))

	if _, err := f.Write(header); err != nil {
		return err
	}

	row := make([]byte, rowBytes)
	for y := H - 1; y >= 0; y-- {
		i := 0
		for x := 0; x < W; x++ {
			c := toRGB(pix[y*W+x])
			row[i] = c.b
			row[i+1] = c.g
			row[i+2] = c.r
			i += 3
		}
		for ; i < rowBytes; i++ {
			row[i] = 0
		}
		if _, err := f.Write(row); err != nil {
			return err
		}
	}

	return nil
}

// ============================================================
// Helpers
// ============================================================

func idxOf(x, y int) int {
	return y*W + x
}

func wrap(x, m int) int {
	if x < 0 {
		return x + m
	}
	if x >= m {
		return x - m
	}
	return x
}

// ============================================================
// Serializable RNG (xorshift64*)
// ============================================================

type RNG struct {
	State uint64
}

func newRNG(seed uint64) RNG {
	if seed == 0 {
		seed = 0x9e3779b97f4a7c15
	}
	return RNG{State: seed}
}

func (r *RNG) Uint64() uint64 {
	x := r.State
	x ^= x >> 12
	x ^= x << 25
	x ^= x >> 27
	r.State = x
	return x * 2685821657736338717
}

func (r *RNG) Intn(n int) int {
	if n <= 0 {
		panic("Intn with n <= 0")
	}
	return int(r.Uint64() % uint64(n))
}

// uniform int in [lo, hi]
func (r *RNG) RangeInt(lo, hi int) int {
	return lo + r.Intn(hi-lo+1)
}

// uniform float64 in [0, 1)
func (r *RNG) Float01() float64 {
	const denom = float64(1 << 53)
	return float64(r.Uint64()>>11) / denom
}

// jitter in [-0.25, 0.25)
func (r *RNG) JitterQuarter() float64 {
	return -0.25 + 0.5*r.Float01()
}

// ============================================================
// Layer
// ============================================================

type Layer struct {
	Occ     []byte
	Color   Color
	RNG     RNG
	CenterX int     // fixed seed-point location this layer grows from
	CenterY int
	Radius  float64 // current max distance from center to any stuck pixel
}

func newLayer() Layer {
	return Layer{
		Occ:   make([]byte, W*H),
		Color: WHITE,
		RNG:   newRNG(1),
	}
}

// spawnPoint returns a launch position on a ring just outside the layer's
// current cluster radius, so new walkers start close enough to actually
// reach the cluster within MaxSteps regardless of how large it's grown.
func (L *Layer) spawnPoint() (int, int) {
	r := L.Radius + SpawnMargin
	if r < SpawnMargin {
		r = SpawnMargin
	}
	angle := L.RNG.Float01() * 2 * math.Pi
	sx := float64(L.CenterX) + r*math.Cos(angle)
	sy := float64(L.CenterY) + r*math.Sin(angle)
	return wrap(int(math.Round(sx)), W), wrap(int(math.Round(sy)), H)
}

// updateRadius grows the tracked cluster radius if (x, y) is farther from
// center than anything stuck so far.
func (L *Layer) updateRadius(x, y int) {
	// Find the shortest path along the X axis (allowing for screen wrap)
	dx := math.Abs(float64(x - L.centerX))
	if dx > float64(W)/2.0 {
		dx = float64(W) - dx
	}

	// Find the shortest path along the Y axis
	dy := math.Abs(float64(y - L.centerY))
	if dy > float64(H)/2.0 {
		dy = float64(H) - dy
	}

	// Calculate true periodic distance
	d := math.Hypot(dx, dy)
	if d > L.radius {
		L.radius = d
	}
}

// estimateCenterRadius derives an approximate center and radius directly
// from an occupancy bitmap. Used as a graceful fallback when resuming from
// a checkpoint written before Center/Radius were tracked explicitly — the
// exact original seed point can't be recovered, but the centroid of
// already-stuck pixels is a good stand-in since the cluster is already
// roughly compact around it.
func estimateCenterRadius(occ []byte) (cx, cy int, radius float64) {
	var sumX, sumY, n int64
	for y := 0; y < H; y++ {
		for x := 0; x < W; x++ {
			if occ[idxOf(x, y)] != 0 {
				sumX += int64(x)
				sumY += int64(y)
				n++
			}
		}
	}
	if n == 0 {
		return W / 2, H / 2, 0
	}
	cx = int(sumX / n)
	cy = int(sumY / n)
	for y := 0; y < H; y++ {
		for x := 0; x < W; x++ {
			if occ[idxOf(x, y)] != 0 {
				d := math.Hypot(float64(x-cx), float64(y-cy))
				if d > radius {
					radius = d
				}
			}
		}
	}
	return cx, cy, radius
}

// ============================================================
// Checkpoint I/O
// ============================================================

type checkpointJSON struct {
	Frame int `json:"frame"`
}

func saveCheckpoint(dir string, frame int, layers []Layer) error {
	jpath := filepath.Join(dir, "checkpoint.json")
	bpath := filepath.Join(dir, "checkpoint.bin")

	jf, err := os.Create(jpath)
	if err != nil {
		return err
	}
	enc := json.NewEncoder(jf)
	enc.SetIndent("", "  ")
	if err := enc.Encode(checkpointJSON{Frame: frame}); err != nil {
		_ = jf.Close()
		return err
	}
	if err := jf.Close(); err != nil {
		return err
	}

	bf, err := os.Create(bpath)
	if err != nil {
		return err
	}
	defer bf.Close()

	for _, L := range layers {
		if len(L.Occ) != W*H {
			return fmt.Errorf("invalid layer occupancy length")
		}
		if _, err := bf.Write(L.Occ); err != nil {
			return err
		}
		if err := binary.Write(bf, binary.LittleEndian, L.RNG.State); err != nil {
			return err
		}
		if err := binary.Write(bf, binary.LittleEndian, int32(L.CenterX)); err != nil {
			return err
		}
		if err := binary.Write(bf, binary.LittleEndian, int32(L.CenterY)); err != nil {
			return err
		}
		if err := binary.Write(bf, binary.LittleEndian, L.Radius); err != nil {
			return err
		}
	}

	return nil
}

// loadCheckpoint reads Occ + RNG state for each layer, then attempts to
// read the trailing Center/Radius fields. If those are missing (a
// checkpoint written by an older build, before this format extension),
// it falls back to estimating them from the occupancy bitmap rather than
// failing outright.
func loadCheckpoint(dir string, frame *int, layers []Layer) (bool, error) {
	jpath := filepath.Join(dir, "checkpoint.json")
	bpath := filepath.Join(dir, "checkpoint.bin")

	jf, err := os.Open(jpath)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}
	defer jf.Close()

	bf, err := os.Open(bpath)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}
	defer bf.Close()

	var cj checkpointJSON
	if err := json.NewDecoder(jf).Decode(&cj); err != nil {
		return false, err
	}
	*frame = cj.Frame

	for i := range layers {
		if _, err := io.ReadFull(bf, layers[i].Occ); err != nil {
			return false, err
		}
		if err := binary.Read(bf, binary.LittleEndian, &layers[i].RNG.State); err != nil {
			return false, err
		}

		var cx, cy int32
		var radius float64
		cxErr := binary.Read(bf, binary.LittleEndian, &cx)
		cyErr := binary.Read(bf, binary.LittleEndian, &cy)
		radErr := binary.Read(bf, binary.LittleEndian, &radius)
		if cxErr != nil || cyErr != nil || radErr != nil {
			// Older checkpoint format without Center/Radius — estimate
			// from the occupancy bitmap instead of failing.
			ecx, ecy, erad := estimateCenterRadius(layers[i].Occ)
			fmt.Printf(
				"Layer %d: checkpoint predates center/radius tracking — "+
					"estimated center=(%d,%d) radius=%.1f from occupancy\n",
				i, ecx, ecy, erad,
			)
			layers[i].CenterX, layers[i].CenterY, layers[i].Radius = ecx, ecy, erad
		} else {
			layers[i].CenterX, layers[i].CenterY, layers[i].Radius = int(cx), int(cy), radius
		}
	}

	return true, nil
}

// ============================================================
// Thickening (post-process, Euclidean)
// ============================================================

func thicken(src []byte, out []byte) {
	for i := range out {
		out[i] = 0
	}

	for y := 0; y < H; y++ {
		for x := 0; x < W; x++ {
			if src[idxOf(x, y)] != 0 {
				for dy := -ThickRad; dy <= ThickRad; dy++ {
					for dx := -ThickRad; dx <= ThickRad; dx++ {
						if dx*dx+dy*dy <= ThickRad*ThickRad {
							out[idxOf(wrap(x+dx, W), wrap(y+dy, H))] = 1
						}
					}
				}
			}
		}
	}
}

// ============================================================
// Seed helper
// ============================================================

func randomSeed64() uint64 {
	var b [8]byte
	if _, err := rand.Read(b[:]); err == nil {
		return binary.LittleEndian.Uint64(b[:])
	}
	return uint64(time.Now().UnixNano())
}

// ============================================================
// Main
// ============================================================

func usage() {
	fmt.Fprintln(os.Stderr, "Usage:\n  ./dla out --init [--seed N]\n  ./dla out --to N [--seed N]")
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}

	outDir := os.Args[1]
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		fmt.Fprintln(os.Stderr, "Failed to create output directory:", err)
		os.Exit(1)
	}

	initOnly := false
	targetFrame := 100
	haveTo := false
	var seedOverride uint64
	haveSeed := false

	// Manual flag scan (not using the `flag` package, since args can
	// appear in any order/combination: --init, --to N, --seed N).
	args := os.Args[2:]
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--init":
			initOnly = true
		case "--to":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, "Bad args: --to requires a frame number")
				os.Exit(1)
			}
			n, err := strconv.Atoi(args[i+1])
			if err != nil {
				fmt.Fprintln(os.Stderr, "Bad frame number")
				os.Exit(1)
			}
			targetFrame = n
			haveTo = true
			i++
		case "--seed":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, "Bad args: --seed requires a value")
				os.Exit(1)
			}
			n, err := strconv.ParseUint(args[i+1], 10, 64)
			if err != nil {
				fmt.Fprintln(os.Stderr, "Bad seed value")
				os.Exit(1)
			}
			seedOverride = n
			haveSeed = true
			i++
		default:
			fmt.Fprintln(os.Stderr, "Bad args:", args[i])
			usage()
			os.Exit(1)
		}
	}
	if !initOnly && !haveTo {
		usage()
		os.Exit(1)
	}

	layers := make([]Layer, 5)
	for i := range layers {
		layers[i] = newLayer()
	}
	pal := [5]Color{BLUE, GREEN, RED, YELLOW, BLACK}

	initSeed := seedOverride
	if !haveSeed || initSeed == 0 {
		initSeed = randomSeed64()
	}

	curFrame := 0

	if !initOnly {
		ok, err := loadCheckpoint(outDir, &curFrame, layers)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Failed to load checkpoint:", err)
			os.Exit(1)
		}
		if ok {
			fmt.Printf("Resuming from frame %d\n", curFrame)
			for i := 0; i < 5; i++ {
				layers[i].Color = pal[i]
			}
		} else {
			initializeLayers(layers, pal, initSeed)
			fmt.Printf("Initializing frame 0 (seed=%d)\n", initSeed)
			if err := saveCheckpoint(outDir, 0, layers); err != nil {
				fmt.Fprintln(os.Stderr, "Failed to save checkpoint:", err)
				os.Exit(1)
			}
		}
	} else {
		initializeLayers(layers, pal, initSeed)
		fmt.Printf("Initializing frame 0 (seed=%d)\n", initSeed)
		if err := saveCheckpoint(outDir, 0, layers); err != nil {
			fmt.Fprintln(os.Stderr, "Failed to save checkpoint:", err)
			os.Exit(1)
		}
		return
	}

	for f := curFrame + 1; f <= targetFrame; f++ {
		for li := range layers {
			L := &layers[li]
			for p := 0; p < WalkersPF; p++ {
				x, y := L.spawnPoint()

				stuck := false
				for s := 0; s < MaxSteps; s++ {
					var dx, dy int
					for {
						dx = L.RNG.RangeInt(-1, 1)
						dy = L.RNG.RangeInt(-1, 1)
						if dx != 0 || dy != 0 {
							break
						}
					}

					x = wrap(x+dx, W)
					y = wrap(y+dy, H)

					for ny := -1; ny <= 1 && !stuck; ny++ {
						for nx := -1; nx <= 1; nx++ {
							if L.Occ[idxOf(wrap(x+nx, W), wrap(y+ny, H))] != 0 {
								L.Occ[idxOf(x, y)] = 1
								stuck = true
								break
							}
						}
					}

					if stuck {
						L.updateRadius(x, y)
						break
					}
				}
			}
		}

		if err := saveCheckpoint(outDir, f, layers); err != nil {
			fmt.Fprintln(os.Stderr, "Failed to save checkpoint:", err)
			os.Exit(1)
		}
	}

	img := make([]Color, W*H)
	for i := range img {
		img[i] = WHITE
	}
	thick := make([]byte, W*H)

	for i := 0; i < 5; i++ {
		thicken(layers[i].Occ, thick)
		for p := 0; p < W*H; p++ {
			if thick[p] != 0 {
				img[p] = layers[i].Color
			}
		}
	}

	bmpPath := filepath.Join(outDir, "current.bmp")
	if err := writeBMP24(bmpPath, img); err != nil {
		fmt.Fprintln(os.Stderr, "Failed to write BMP:", err)
		os.Exit(1)
	}

	fmt.Printf("Done. Frame %d saved.\n", targetFrame)
}

func initializeLayers(layers []Layer, pal [5]Color, seed uint64) {
	base := newRNG(seed)

	cols := 3
	rows := 2
	idx := 0

	for r := 0; r < rows && idx < 5; r++ {
		for c := 0; c < cols && idx < 5; c++ {
			x := int((float64(c)+0.5+base.JitterQuarter()) * float64(W) / float64(cols))
			y := int((float64(r)+0.5+base.JitterQuarter()) * float64(H) / float64(rows))

			// Clamp just in case floating-point jitter lands on an edge
			if x < 0 {
				x = 0
			}
			if x >= W {
				x = W - 1
			}
			if y < 0 {
				y = 0
			}
			if y >= H {
				y = H - 1
			}

			layers[idx].Color = pal[idx]
			layers[idx].Occ[idxOf(x, y)] = 1
			layers[idx].RNG = newRNG(seed + uint64(idx))
			layers[idx].CenterX = x
			layers[idx].CenterY = y
			layers[idx].Radius = 0
			idx++
		}
	}
}
