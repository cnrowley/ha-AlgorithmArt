package main

import (
    "encoding/binary"
    "encoding/json"
    "fmt"
    "image"
    "image/color"
    "io"
    "math"
    "os"
    "path/filepath"
    "strconv"
    "time"

    "golang.org/x/image/bmp"
)

// ============================================================
// Configuration
// ============================================================

const (
    W         = 800
    H         = 480
    NumLayers = 5

    WalkersPerFrame = 1200
    MaxSteps        = 6000

    // Visual thickening only; does not affect growth.
    ThickRad = 3

    // Walkers are launched this far outside the current cluster radius.
    SpawnMargin = 30.0

    // If a walker wanders too far away from its own layer cluster,
    // abandon it. This keeps walks local and avoids wasting steps.
    KillMargin = 120.0
)

// ============================================================
// Colour
// ============================================================

type Color uint8

const (
    WHITE Color = iota
    BLUE
    GREEN
    RED
    ORANGE
    PURPLE
)

func toRGBA(c Color) color.RGBA {
    switch c {
    case BLUE:
        return color.RGBA{0, 0, 255, 255}
    case GREEN:
        return color.RGBA{0, 200, 0, 255}
    case RED:
        return color.RGBA{220, 0, 0, 255}
    case ORANGE:
        return color.RGBA{255, 140, 0, 255}
    case PURPLE:
        return color.RGBA{150, 0, 220, 255}
    default:
        return color.RGBA{255, 255, 255, 255}
    }
}

// ============================================================
// Helpers
// ============================================================

func idxOf(x, y int) int {
    return y*W + x
}

func wrap(x, m int) int {
    x %= m
    if x < 0 {
        x += m
    }
    return x
}

func periodicDelta(a, b, m int) float64 {
    d := math.Abs(float64(a - b))
    if d > float64(m)/2.0 {
        d = float64(m) - d
    }
    return d
}

func periodicDistance(x, y, cx, cy int) float64 {
    dx := periodicDelta(x, cx, W)
    dy := periodicDelta(y, cy, H)
    return math.Hypot(dx, dy)
}

func countOcc(occ []byte) int {
    n := 0
    for _, v := range occ {
        if v != 0 {
            n++
        }
    }
    return n
}

// ============================================================
// RNG: xorshift64*
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

func (r *RNG) RangeInt(lo, hi int) int {
    return lo + r.Intn(hi-lo+1)
}

func (r *RNG) Float01() float64 {
    const denom = float64(uint64(1) << 53)
    return float64(r.Uint64()>>11) / denom
}

func (r *RNG) JitterQuarter() float64 {
    return -0.25 + 0.5*r.Float01()
}

// SplitMix64-style seed scrambling.
func splitSeed(x uint64) uint64 {
    x += 0x9e3779b97f4a7c15
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9
    x = (x ^ (x >> 27)) * 0x94d049bb133111eb
    return x ^ (x >> 31)
}

// ============================================================
// Layer
// ============================================================

type Layer struct {
    Occ     []byte
    Color   Color
    RNG     RNG
    CenterX int
    CenterY int
    Radius  float64
}

func newLayer(color Color, seed uint64, cx, cy int) Layer {
    L := Layer{
        Occ:     make([]byte, W*H),
        Color:   color,
        RNG:     newRNG(seed),
        CenterX: cx,
        CenterY: cy,
        Radius:  0,
    }

    L.Occ[idxOf(cx, cy)] = 1
    return L
}

func (L *Layer) spawnPoint() (int, int) {
    r := L.Radius + SpawnMargin
    if r < SpawnMargin {
        r = SpawnMargin
    }

    theta := L.RNG.Float01() * 2.0 * math.Pi

    x := float64(L.CenterX) + r*math.Cos(theta)
    y := float64(L.CenterY) + r*math.Sin(theta)

    return wrap(int(math.Round(x)), W), wrap(int(math.Round(y)), H)
}

func (L *Layer) updateRadius(x, y int) {
    d := periodicDistance(x, y, L.CenterX, L.CenterY)
    if d > L.Radius {
        L.Radius = d
    }
}

func (L *Layer) shouldKill(x, y int) bool {
    limit := L.Radius + SpawnMargin + KillMargin
    return periodicDistance(x, y, L.CenterX, L.CenterY) > limit
}

func (L *Layer) hasOccupiedNeighbour(x, y int) bool {
    for dy := -1; dy <= 1; dy++ {
        for dx := -1; dx <= 1; dx++ {
            if dx == 0 && dy == 0 {
                continue
            }

            xx := wrap(x+dx, W)
            yy := wrap(y+dy, H)

            if L.Occ[idxOf(xx, yy)] != 0 {
                return true
            }
        }
    }

    return false
}

func (L *Layer) addWalker() bool {
    x, y := L.spawnPoint()

    for s := 0; s < MaxSteps; s++ {
        dx, dy := 0, 0

        for dx == 0 && dy == 0 {
            dx = L.RNG.RangeInt(-1, 1)
            dy = L.RNG.RangeInt(-1, 1)
        }

        x = wrap(x+dx, W)
        y = wrap(y+dy, H)

        if L.shouldKill(x, y) {
            return false
        }

        if L.hasOccupiedNeighbour(x, y) {
            L.Occ[idxOf(x, y)] = 1
            L.updateRadius(x, y)
            return true
        }
    }

    return false
}

// ============================================================
// Thickening
// ============================================================

func thicken(src []byte, out []byte) {
    for i := range out {
        out[i] = 0
    }

    for y := 0; y < H; y++ {
        for x := 0; x < W; x++ {
            if src[idxOf(x, y)] == 0 {
                continue
            }

            for dy := -ThickRad; dy <= ThickRad; dy++ {
                for dx := -ThickRad; dx <= ThickRad; dx++ {
                    if dx*dx+dy*dy <= ThickRad*ThickRad {
                        xx := wrap(x+dx, W)
                        yy := wrap(y+dy, H)
                        out[idxOf(xx, yy)] = 1
                    }
                }
            }
        }
    }
}

// ============================================================
// Initialization
// ============================================================

func initializeLayers(seed uint64) []Layer {
    base := newRNG(splitSeed(seed))

    // Draw order. These are all saturated colours and avoid pure black,
    // which can dominate on limited or thresholding display pipelines.
    palette := []Color{
        BLUE,
        GREEN,
        RED,
        ORANGE,
        PURPLE,
    }

    layers := make([]Layer, 0, NumLayers)

    cols := 3
    rows := 2
    i := 0

    for r := 0; r < rows && i < NumLayers; r++ {
        for c := 0; c < cols && i < NumLayers; c++ {
            x := int((float64(c)+0.5+base.JitterQuarter()) * float64(W) / float64(cols))
            y := int((float64(r)+0.5+base.JitterQuarter()) * float64(H) / float64(rows))

            x = wrap(x, W)
            y = wrap(y, H)

            layerSeed := splitSeed(seed + uint64(i+1)*0x9e3779b97f4a7c15)

            L := newLayer(palette[i], layerSeed, x, y)
            layers = append(layers, L)

            i++
        }
    }

    return layers
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

    if err := binary.Write(bf, binary.LittleEndian, uint32(len(layers))); err != nil {
        return err
    }

    for _, L := range layers {
        if len(L.Occ) != W*H {
            return fmt.Errorf("bad occupancy length")
        }

        if _, err := bf.Write(L.Occ); err != nil {
            return err
        }

        if err := binary.Write(bf, binary.LittleEndian, uint8(L.Color)); err != nil {
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

func loadCheckpoint(dir string, frame *int, layers *[]Layer) (bool, error) {
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

    var n uint32
    if err := binary.Read(bf, binary.LittleEndian, &n); err != nil {
        return false, err
    }

    if n != NumLayers {
        return false, fmt.Errorf("checkpoint has %d layers, expected %d", n, NumLayers)
    }

    loaded := make([]Layer, NumLayers)

    for i := 0; i < NumLayers; i++ {
        loaded[i].Occ = make([]byte, W*H)

        if _, err := io.ReadFull(bf, loaded[i].Occ); err != nil {
            return false, err
        }

        var c uint8
        if err := binary.Read(bf, binary.LittleEndian, &c); err != nil {
            return false, err
        }
        loaded[i].Color = Color(c)

        if err := binary.Read(bf, binary.LittleEndian, &loaded[i].RNG.State); err != nil {
            return false, err
        }

        var cx, cy int32

        if err := binary.Read(bf, binary.LittleEndian, &cx); err != nil {
            return false, err
        }

        if err := binary.Read(bf, binary.LittleEndian, &cy); err != nil {
            return false, err
        }

        if err := binary.Read(bf, binary.LittleEndian, &loaded[i].Radius); err != nil {
            return false, err
        }

        loaded[i].CenterX = int(cx)
        loaded[i].CenterY = int(cy)
    }

    *layers = loaded
    return true, nil
}

// ============================================================
// Rendering using golang.org/x/image/bmp
// ============================================================

func renderComposite(outDir string, layers []Layer) error {
    img := image.NewRGBA(image.Rect(0, 0, W, H))

    white := toRGBA(WHITE)

    for y := 0; y < H; y++ {
        for x := 0; x < W; x++ {
            img.SetRGBA(x, y, white)
        }
    }

    thick := make([]byte, W*H)

    // Stacked composite. Later layers overwrite earlier layers only
    // where their thickened pixels overlap.
    for i := range layers {
        thicken(layers[i].Occ, thick)

        col := toRGBA(layers[i].Color)

        for y := 0; y < H; y++ {
            for x := 0; x < W; x++ {
                p := idxOf(x, y)

                if thick[p] != 0 {
                    img.SetRGBA(x, y, col)
                }
            }
        }
    }

    outPath := filepath.Join(outDir, "current.bmp")

    f, err := os.Create(outPath)
    if err != nil {
        return err
    }
    defer f.Close()

    return bmp.Encode(f, img)
}

// ============================================================
// CLI
// ============================================================

func usage() {
    fmt.Fprintln(os.Stderr, "Usage:")
    fmt.Fprintln(os.Stderr, "  ./dla.x out --init [--seed S]")
    fmt.Fprintln(os.Stderr, "  ./dla.x out --to N [--seed S]")
}

// ============================================================
// Main
// ============================================================

func main() {
    if len(os.Args) < 3 {
        usage()
        os.Exit(1)
    }

    outDir := os.Args[1]

    if err := os.MkdirAll(outDir, 0o755); err != nil {
        fmt.Fprintln(os.Stderr, "Failed to create output directory:", err)
        os.Exit(1)
    }

    initOnly := false
    targetFrame := -1

    var seed uint64
    haveSeed := false

    args := os.Args[2:]

    for i := 0; i < len(args); i++ {
        switch args[i] {
        case "--init":
            initOnly = true

        case "--to":
            if i+1 >= len(args) {
                fmt.Fprintln(os.Stderr, "--to requires a frame number")
                os.Exit(1)
            }

            n, err := strconv.Atoi(args[i+1])
            if err != nil || n < 0 {
                fmt.Fprintln(os.Stderr, "Bad frame number")
                os.Exit(1)
            }

            targetFrame = n
            i++

        case "--seed":
            if i+1 >= len(args) {
                fmt.Fprintln(os.Stderr, "--seed requires a value")
                os.Exit(1)
            }

            n, err := strconv.ParseUint(args[i+1], 10, 64)
            if err != nil {
                fmt.Fprintln(os.Stderr, "Bad seed value")
                os.Exit(1)
            }

            seed = n
            haveSeed = true
            i++

        default:
            fmt.Fprintln(os.Stderr, "Bad arg:", args[i])
            usage()
            os.Exit(1)
        }
    }

    if initOnly && targetFrame >= 0 {
        fmt.Fprintln(os.Stderr, "Use either --init or --to N, not both")
        os.Exit(1)
    }

    if !initOnly && targetFrame < 0 {
        usage()
        os.Exit(1)
    }

    if !haveSeed {
        seed = uint64(time.Now().UnixNano())
    }

    var layers []Layer
    curFrame := 0

    if initOnly {
        fmt.Printf("Initializing frame 0 with seed %d\n", seed)

        layers = initializeLayers(seed)

        for i := range layers {
            fmt.Printf(
                "Layer %d: start=(%d,%d), seed=%d\n",
                i,
                layers[i].CenterX,
                layers[i].CenterY,
                layers[i].RNG.State,
            )
        }

        if err := saveCheckpoint(outDir, 0, layers); err != nil {
            fmt.Fprintln(os.Stderr, "Failed to save checkpoint:", err)
            os.Exit(1)
        }

        if err := renderComposite(outDir, layers); err != nil {
            fmt.Fprintln(os.Stderr, "Failed to write BMP:", err)
            os.Exit(1)
        }

        fmt.Printf("Done. Wrote %s\n", filepath.Join(outDir, "current.bmp"))
        return
    }

    ok, err := loadCheckpoint(outDir, &curFrame, &layers)
    if err != nil {
        fmt.Fprintln(os.Stderr, "Failed to load checkpoint:", err)
        os.Exit(1)
    }

    if ok {
        fmt.Printf("Resuming from frame %d\n", curFrame)
    } else {
        fmt.Printf("No checkpoint found; initializing frame 0 with seed %d\n", seed)

        layers = initializeLayers(seed)
        curFrame = 0

        for i := range layers {
            fmt.Printf(
                "Layer %d: start=(%d,%d), seed=%d\n",
                i,
                layers[i].CenterX,
                layers[i].CenterY,
                layers[i].RNG.State,
            )
        }

        if err := saveCheckpoint(outDir, 0, layers); err != nil {
            fmt.Fprintln(os.Stderr, "Failed to save checkpoint:", err)
            os.Exit(1)
        }
    }

    if targetFrame < curFrame {
        fmt.Fprintf(
            os.Stderr,
            "Target frame %d is before current checkpoint frame %d\n",
            targetFrame,
            curFrame,
        )
        os.Exit(1)
    }

    for f := curFrame + 1; f <= targetFrame; f++ {
        fmt.Printf("Frame %d:", f)

        for li := range layers {
            stuck := 0

            for p := 0; p < WalkersPerFrame; p++ {
                if layers[li].addWalker() {
                    stuck++
                }
            }

            fmt.Printf(
                " L%d stuck=%d total=%d r=%.1f",
                li,
                stuck,
                countOcc(layers[li].Occ),
                layers[li].Radius,
            )
        }

        fmt.Println()

        if err := saveCheckpoint(outDir, f, layers); err != nil {
            fmt.Fprintln(os.Stderr, "Failed to save checkpoint:", err)
            os.Exit(1)
        }
    }

    if err := renderComposite(outDir, layers); err != nil {
        fmt.Fprintln(os.Stderr, "Failed to write BMP:", err)
        os.Exit(1)
    }

    fmt.Printf("Done. Frame %d written to %s\n", targetFrame, filepath.Join(outDir, "current.bmp"))
}
