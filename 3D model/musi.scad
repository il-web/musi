// =============================================================
//  musi — 3.5" iPod-style music player
//  VISUAL CONCEPT model (not printable yet — shape & style only)
//
//  Hardware represented:
//    - 3.5" 320x480 touchscreen (ST7796)
//    - 5-button circular cluster (up/down/left/right + center select)
//    - power button (top edge), USB-C port (bottom edge)
//
//  Front face points +Z up: press F5 to see the front.
// =============================================================

$fn = 96;                  // smoothness for curves

// ---------- BODY ----------
body_w   = 70;             // width  (X)
body_h   = 120;            // height (Y)
body_d   = 19;             // depth / thickness (Z)
edge_r   = 1.5;            // tiny edge break — "flat sides, crisp corners"

// ---------- SCREEN (screen-maximal layout) ----------
glass_w      = 60;         // visible black glass panel width
glass_h      = 78;         // visible black glass panel height
glass_top_gap = 6;         // gap from top edge of body to top of glass
glass_sink   = 0.6;        // how deep the glass sits below the face

active_w     = 49;         // 320x480 active display area
active_h     = 73;

// ---------- BUTTON CLUSTER ----------
ring_outer   = 30;         // outer diameter of the control ring
ring_inner   = 14;         // inner hole of the ring (around select)
ring_depth   = 1.6;        // how far the ring sinks into the face
select_d     = 12;         // center select button diameter
cluster_cy   = 18;         // ring center height, measured from BOTTOM edge

// ---------- EDGE FEATURES ----------
power_w      = 9;          // power button (pill) on TOP edge
power_h      = 4;
power_off_x  = 18;         // offset right-of-center on the top edge

usbc_w       = 9.5;        // USB-C slot on BOTTOM edge
usbc_h       = 3.4;

// ---------- COLORS ----------
col_body   = [0.28, 0.29, 0.32];   // space gray
col_glass  = [0.05, 0.05, 0.06];   // near black
col_active = [0.10, 0.13, 0.20];   // dark blue-gray (display lit hint)
col_btn    = [0.78, 0.80, 0.83];   // light gray buttons
col_accent = [0.55, 0.57, 0.60];   // ring / marks

// =============================================================
//  MODULES
// =============================================================

// Rounded-edge box centered in X/Y, sitting on Z=0..d.
// Small radius => flat sides with crisp (lightly broken) corners.
module rbox(w, h, d, r) {
    hull() {
        for (x = [-w/2 + r, w/2 - r])
            for (y = [-h/2 + r, h/2 - r])
                for (z = [r, d - r])
                    translate([x, y, z]) sphere(r);
    }
}

module body_shell() {
    color(col_body) rbox(body_w, body_h, body_d, edge_r);
}

// Black glass panel + faint active-area, recessed into the front face.
module screen_panel() {
    // Y center of glass: top of glass is glass_top_gap below the top edge.
    gy = body_h/2 - glass_top_gap - glass_h/2;

    // recess pocket (subtract a thin slab so glass sits below face)
    translate([0, gy, body_d - glass_sink])
        color(col_glass) cube([glass_w, glass_h, glass_sink * 2 + 0.2], center = true);

    // faint lit display area, just under the glass surface
    translate([0, gy, body_d - glass_sink - 0.1])
        color(col_active) cube([active_w, active_h, 0.4], center = true);
}

// Circular control ring + center select, recessed into the lower face.
module dpad_cluster() {
    cy = -body_h/2 + cluster_cy;     // ring center, from bottom edge

    translate([0, cy, body_d - ring_depth]) {
        // recessed ring (annulus)
        color(col_accent)
        linear_extrude(ring_depth + 0.1)
            difference() {
                circle(d = ring_outer);
                circle(d = ring_inner);
            }

        // clean triangular direction marks on the ring (up/down/left/right)
        rm = (ring_outer + ring_inner) / 4;   // mid-radius of the ring
        color(col_btn)
        for (a = [0, 90, 180, 270])
            rotate([0, 0, a])
                translate([0, rm, ring_depth])
                    linear_extrude(0.7)
                        polygon([[-2, -1.8], [2, -1.8], [0, 2.0]]);  // arrow, tip outward
    }

    // center select button — fills the ring hole at its base, domes up to select_d
    translate([0, cy, body_d - ring_depth])
        color(col_btn)
        cylinder(h = ring_depth + 0.9, d1 = ring_inner + 0.2, d2 = select_d);
}

// Power button: pill on the TOP edge (toward the right).
module power_button() {
    translate([power_off_x, body_h/2, body_d/2])
        color(col_btn)
        rotate([90, 0, 0])
            hull() {
                for (x = [-power_w/2 + power_h/2, power_w/2 - power_h/2])
                    translate([x, 0, 0]) cylinder(h = 2.5, d = power_h, center = true);
            }
}

// USB-C: rounded slot on the BOTTOM edge, centered.
module usbc_port() {
    translate([0, -body_h/2, body_d/2])
        color(col_glass)
        rotate([90, 0, 0])
            hull() {
                for (x = [-usbc_w/2 + usbc_h/2, usbc_w/2 - usbc_h/2])
                    translate([x, 0, 0]) cylinder(h = 4, d = usbc_h, center = true);
            }
}

// =============================================================
//  ASSEMBLY
// =============================================================
module musi() {
    difference() {
        body_shell();
        // carve the screen recess pocket out of the body
        gy = body_h/2 - glass_top_gap - glass_h/2;
        translate([0, gy, body_d - glass_sink])
            cube([glass_w, glass_h, glass_sink * 2], center = true);
        // carve the ring recess out of the body
        cy = -body_h/2 + cluster_cy;
        translate([0, cy, body_d - ring_depth/2])
            cylinder(h = ring_depth + 0.1, d = ring_outer, center = true);
    }
    screen_panel();
    dpad_cluster();
    power_button();
    usbc_port();
}

musi();
