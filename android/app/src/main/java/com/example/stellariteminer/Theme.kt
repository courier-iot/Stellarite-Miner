package com.example.stellariteminer

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorFilter
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.util.AttributeSet
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.TextView

/**
 * "Neon Pulsar" theme: pure black, neon crimson, amber highlights, HUD brackets, scanlines.
 *
 * Fonts: Orbitron (display) and Share Tech Mono (body) are loaded from
 * assets/fonts/ when present (the GitHub build downloads them); otherwise the
 * app falls back to the phone's condensed sans and monospace fonts.
 */
object Theme {
    val BLACK = Color.parseColor("#030303")
    val PANEL = Color.parseColor("#0A0A0A")
    val CRIMSON = Color.parseColor("#DC143C")
    val CRIMSON_LIGHT = Color.parseColor("#FF4D6A")  // crimson tint for small text on black
    val CRIMSON_DIM = Color.parseColor("#3A0A14")
    val AMBER = Color.parseColor("#FBBF24")
    val TEXT = Color.parseColor("#F2F2F2")
    val MUTED = Color.parseColor("#9A9A9A")

    private var display: Typeface? = null
    private var heavy: Typeface? = null
    private var mono: Typeface? = null

    private fun load(ctx: Context) {
        if (mono != null) return
        fun orbitron(weight: Int): Typeface? = try {
            Typeface.Builder(ctx.assets, "fonts/Orbitron.ttf")
                .setFontVariationSettings("'wght' $weight").build()
        } catch (e: Exception) { null }
        display = orbitron(700) ?: Typeface.create("sans-serif-condensed", Typeface.BOLD)
        heavy = orbitron(900) ?: Typeface.create("sans-serif-condensed", Typeface.BOLD)
        mono = try {
            Typeface.createFromAsset(ctx.assets, "fonts/ShareTechMono-Regular.ttf")
        } catch (e: Exception) { Typeface.MONOSPACE }
    }

    /** Applies fonts through a view tree: tag="display" or "heavy" for headings, mono otherwise. */
    fun applyFonts(root: View) {
        load(root.context)
        if (root is TextView) {
            root.typeface = when (root.tag) {
                "display" -> display
                "heavy" -> heavy
                else -> mono
            }
        }
        if (root is ViewGroup) for (i in 0 until root.childCount) applyFonts(root.getChildAt(i))
    }

    /** Neon glow on text. */
    fun glow(tv: TextView, radius: Float = 18f) = tv.setShadowLayer(radius, 0f, 0f, CRIMSON)

    fun dp(ctx: Context, v: Float) = v * ctx.resources.displayMetrics.density
}

/** Button background with two chamfered corners, filled or outlined. */
class ChamferDrawable(private val density: Float, var filled: Boolean) : Drawable() {
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Theme.CRIMSON }
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Theme.CRIMSON; style = Paint.Style.STROKE; strokeWidth = 2 * density
    }
    var pressed = false

    override fun draw(canvas: Canvas) {
        val b = bounds
        val c = 14 * density
        val h = stroke.strokeWidth / 2
        val p = Path().apply {
            moveTo(b.left + c, b.top + h); lineTo(b.right - h, b.top + h)
            lineTo(b.right - h, b.bottom - c); lineTo(b.right - c, b.bottom - h)
            lineTo(b.left + h, b.bottom - h); lineTo(b.left + h, b.top + c); close()
        }
        fill.alpha = when { filled && pressed -> 200; filled -> 255; pressed -> 60; else -> 0 }
        canvas.drawPath(p, fill)
        canvas.drawPath(p, stroke)
    }

    override fun onStateChange(state: IntArray): Boolean {
        val now = state.contains(android.R.attr.state_pressed)
        if (now != pressed) { pressed = now; invalidateSelf(); return true }
        return false
    }

    override fun isStateful() = true
    override fun setAlpha(alpha: Int) {}
    override fun setColorFilter(cf: ColorFilter?) {}
    @Deprecated("Deprecated in Java")
    override fun getOpacity() = PixelFormat.TRANSLUCENT
}

/** Concentric crimson rings with a rotating amber arc while mining. */
class PulseRingView @JvmOverloads constructor(ctx: Context, attrs: AttributeSet? = null) : View(ctx, attrs) {
    private val d = resources.displayMetrics.density
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = Theme.CRIMSON }
    private val arc = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; color = Theme.AMBER; strokeWidth = 2 * d; strokeCap = Paint.Cap.ROUND
    }
    private val dashed = DashPathEffect(floatArrayOf(4 * d, 6 * d), 0f)
    private var angle = -90f
    private var pulse = 0f

    var active = false
        set(v) { field = v; invalidate() }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f
        val r = minOf(width, height) / 2f - 4 * d

        ring.pathEffect = null; ring.strokeWidth = 1 * d; ring.alpha = 46
        canvas.drawCircle(cx, cy, r, ring)
        ring.pathEffect = dashed; ring.alpha = 90
        canvas.drawCircle(cx, cy, r * 0.82f, ring)
        ring.pathEffect = null; ring.strokeWidth = 2 * d
        ring.alpha = if (active) (150 + 100 * pulse).toInt() else 60
        canvas.drawCircle(cx, cy, r * 0.64f, ring)

        canvas.drawArc(RectF(cx - r, cy - r, cx + r, cy + r), angle, 66f, false, arc)

        if (active) {
            angle = (angle + 2.2f) % 360f
            pulse = ((System.currentTimeMillis() % 1600) / 1600f).let { if (it < 0.5f) it * 2 else (1 - it) * 2 }
            postInvalidateOnAnimation()
        }
    }
}

/** Frame that draws crimson HUD corner brackets around its content. */
class HudFrame @JvmOverloads constructor(ctx: Context, attrs: AttributeSet? = null) : FrameLayout(ctx, attrs) {
    private val d = resources.displayMetrics.density
    private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Theme.CRIMSON; strokeWidth = 2 * d; style = Paint.Style.STROKE
    }

    init { setWillNotDraw(false) }

    override fun dispatchDraw(canvas: Canvas) {
        super.dispatchDraw(canvas)
        val l = 18 * d
        val o = p.strokeWidth / 2
        val w = width.toFloat()
        val h = height.toFloat()
        canvas.drawLines(floatArrayOf(
            o, o, l, o, o, o, o, l,
            w - l, o, w - o, o, w - o, o, w - o, l,
            o, h - o, l, h - o, o, h - l, o, h - o,
            w - l, h - o, w - o, h - o, w - o, h - l, w - o, h - o,
        ), p)
    }
}

/** Faint CRT scanlines drawn over the whole screen. Ignores touches. */
class ScanlineView @JvmOverloads constructor(ctx: Context, attrs: AttributeSet? = null) : View(ctx, attrs) {
    private val p = Paint().apply { color = Color.WHITE; alpha = 7 }
    private val gap = 3 * resources.displayMetrics.density

    init { isClickable = false; isFocusable = false; importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO }

    override fun onDraw(canvas: Canvas) {
        var y = 0f
        while (y < height) { canvas.drawRect(0f, y, width.toFloat(), y + 1, p); y += gap }
    }
}
