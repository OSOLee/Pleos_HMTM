package com.example.hmtm.data.bb

/**
 * 질문 화면에서 한 번에 보이는 것 (docs/app-ui.md 2.4, 2.8).
 *  - Single: 보기 하나 고르기 (큰 버튼 2×2)
 *  - Multi: 여러 개 고르기 (운전자 요인·특수 상황). 답은 고른 보기 목록 / [] (답 없음) / ["none"] (해당 없음)
 *  - Bundle: 보기 하나 고르기 질문 여러 개를 한 화면에 (보행자 가감 요소). 서버에는 질문마다 따로 보낸다
 */
sealed class Page {
    abstract val questions: List<Question>

    data class Single(val q: Question) : Page() {
        override val questions get() = listOf(q)
    }

    data class Multi(val q: Question) : Page() {
        override val questions get() = listOf(q)
    }

    data class Bundle(override val questions: List<Question>) : Page()

    val fields get() = questions.map { it.field }
}

/**
 * 한 화면에 묶는 질문 (보기 하나 고르기, 각각 "해당 없음" 값이 있음).
 * 보행자 가감 요소는 늘 셋이 같이 남아 한 화면 "해당하는 것을 모두 고르세요"로 묻는다 (backend-gaps-notes 2절).
 * 묶음의 "해당 없음" = 질문마다 이 값. 서버 질문 정의에는 묶음 표시가 없어 앱이 키로 정한다.
 */
object Bundles {
    val NONE_VALUE: Map<String, Any> = linkedMapOf(
        "parties.other.vulnerable_type" to "none",
        "road.protection_zone" to "none",
        "road.ped_visibility" to "clear",
    )

    /** 묶을 수 있는 질문: 표에 있고, 보기에 "해당 없음" 값이 있고, 조건(depends_on)이 없음 */
    fun bundlable(q: Question): Boolean {
        val none = NONE_VALUE[q.field] ?: return false
        return !q.multi && q.dependsOn.isNullOrEmpty() && q.options.any { Question.sameValue(it, none) }
    }

    /**
     * 화면 순서 맞추기 (답변 고치기는 답한 것 + 남은 것 + 선택 질문을 이어 붙여 순서가 흩어짐):
     * 묶을 질문은 처음 나온 자리에 모으고, 과속 인과관계 질문은 그 당사자 운전자 요인 바로 뒤로
     */
    fun arrange(questions: List<Question>): List<Question> {
        val bundled = questions.filter(::bundlable)
        val follow = questions.filter { FollowUps.isAvoidable(it.field) }
        val out = mutableListOf<Question>()
        for (q in questions) {
            when {
                q in follow -> if (questions.none { it.field == FollowUps.factorsOf(q.field) }) out.add(q)
                q in bundled -> if (q == bundled.first()) out.addAll(bundled)
                else -> {
                    out.add(q)
                    follow.firstOrNull { FollowUps.factorsOf(it.field) == q.field }?.let(out::add)
                }
            }
        }
        return out
    }

    /** 질문 목록 → 화면 목록. 묶을 수 있는 질문이 2개 넘게 이어지면 한 화면으로 */
    fun pages(questions: List<Question>): List<Page> {
        val out = mutableListOf<Page>()
        var run = mutableListOf<Question>()
        fun flush() {
            if (run.size >= 2) out.add(Page.Bundle(run)) else run.forEach { out.add(Page.Single(it)) }
            run = mutableListOf()
        }
        for (q in questions) {
            if (bundlable(q)) {
                run.add(q)
                continue
            }
            flush()
            out.add(if (q.multi) Page.Multi(q) else Page.Single(q))
        }
        flush()
        return out
    }
}

/**
 * 과속 인과관계 질문 (backend-gaps-notes 3절): 서버는 운전자 요인에 과속 보기가 있을 때만 remaining에 넣는다 (when_any,
 * 응답에는 조건이 안 나옴). 답변 고치기에서 운전자 요인을 바꾸면 앱도 같은 조건으로 숨긴다.
 */
object FollowUps {
    private const val AVOIDABLE = ".avoidable_at_limit"
    private const val FACTORS = ".driver_factors"
    val SPEED = setOf("speed_20plus", "speed_under20")

    fun isAvoidable(field: String) = field.startsWith("parties.") && field.endsWith(AVOIDABLE)
    fun factorsOf(avoidable: String) = avoidable.removeSuffix(AVOIDABLE) + FACTORS

    /** 운전자 요인 답에 과속 보기가 있는지 */
    fun speeding(factors: Any?): Boolean = (factors as? List<*>)?.any { it in SPEED } == true
}

/**
 * 질문 화면 한 번 (docs/app-ui.md 2.4). 서버 질문을 한 화면씩 보여 주고, 끝나면 answers()를 PUT한다.
 *
 * - base: 지금까지의 사용자 답 (BbCase.userAnswers). PUT answers는 "지금까지의 답 전부"를 보내야 해서 여기서 시작한다.
 * - picked: 이번에 고른 답. 답변 고치기면 지금 답으로 미리 채운다. 여러 개 고르기는 List.
 * - cleared: "잘 모르겠어요"·건너뛴 묶음 질문. 답을 보내지 않는다 (전에 답했던 것이면 그 답도 뺀다).
 * - known: 판정에 쓴 값 전부 (출처 무관). depends_on 판단에 쓴다.
 * - followUp: 앞 답 때문에 새로 생긴 질문 (과속 → 제한속도를 지켰다면). 화면 머리 글자만 다르다.
 */
data class QuestionSession(
    val caseId: String,
    val questions: List<Question>,
    val base: Map<String, Any?> = emptyMap(),
    val known: Map<String, Any?> = emptyMap(),
    val picked: Map<String, Any?> = emptyMap(),
    val cleared: Set<String> = emptySet(),
    val index: Int = 0,
    val editing: Boolean = false,
    val followUp: Boolean = false,
) {
    val pages: List<Page> = Bundles.pages(questions)

    val page: Page? get() = pages.getOrNull(index)

    /** 지금 화면의 (첫) 질문 */
    val current: Question? get() = page?.questions?.firstOrNull()

    /** 화면 "질문 1 / 2": 지금 조건으로 보일 화면 중 몇 번째인지 */
    val position: Int get() = pages.take(index + 1).count(::visible)
    val total: Int get() = pages.count(::visible)

    /** 한 질문 화면에서 고른 값 */
    val selected: Any? get() = current?.let { picked[it.field] }

    /** "다음"을 누를 수 있는지: 한 질문은 고른 답, 여러 개 고르기는 보기 하나 이상(해당 없음 포함), 묶음은 하나라도 */
    val hasSelection: Boolean
        get() = when (val p = page) {
            is Page.Single -> picked.containsKey(p.q.field)
            is Page.Multi -> (picked[p.q.field] as? List<*>)?.isNotEmpty() == true
            is Page.Bundle -> p.fields.any { picked.containsKey(it) }
            null -> false
        }
    val isLast: Boolean get() = nextIndex(index) == null
    val isFirst: Boolean get() = prevIndex(index) == null

    /** 지금 값: 이번에 고른 답 > 판정에 쓴 값 */
    fun valueOf(field: String): Any? = if (picked.containsKey(field)) picked[field] else known[field]

    /** depends_on 조건이 지금 값으로 맞는지. 조건이 없으면 늘 보임 */
    fun visible(q: Question): Boolean {
        if (FollowUps.isAvoidable(q.field) && !FollowUps.speeding(valueOf(FollowUps.factorsOf(q.field)))) return false
        return q.dependsOn.isNullOrEmpty() || q.dependsOn.all { (f, allowed) ->
            val v = valueOf(f)
            allowed.any { Question.sameValue(it, v) }
        }
    }

    fun visible(p: Page): Boolean = p.questions.any(::visible)

    /** 한 질문 화면: 보기 고르기 */
    fun pick(value: Any?): QuestionSession {
        val q = current ?: return this
        return copy(picked = picked + (q.field to value), cleared = cleared - q.field)
    }

    /** 여러 개 고르기에서 고른 보기 (없으면 빈 목록) */
    fun chosen(field: String): List<Any?> = (picked[field] as? List<*>)?.toList() ?: emptyList()

    /**
     * 여러 개 고르기: 보기를 켜고 끈다. "해당 없음"은 혼자만 (켜면 나머지를 끄고, 다른 보기를 켜면 "해당 없음"을 끔).
     * 모두 끄면 고른 것이 없는 상태 (picked에서 뺌)
     */
    fun toggle(field: String, value: Any?): QuestionSession {
        val now = chosen(field)
        val on = now.any { Question.sameValue(it, value) }
        val next = when {
            on -> now.filterNot { Question.sameValue(it, value) }
            value == Question.NONE -> listOf(Question.NONE)
            else -> now.filterNot { it == Question.NONE } + value
        }
        return if (next.isEmpty()) copy(picked = picked - field)
        else copy(picked = picked + (field to next), cleared = cleared - field)
    }

    /** 묶음에서 "해당 없음"을 고른 상태: 묶음 질문이 모두 그 질문의 "해당 없음" 값 */
    fun bundleNone(p: Page.Bundle): Boolean = p.fields.all { f ->
        picked.containsKey(f) && Question.sameValue(picked[f], Bundles.NONE_VALUE[f])
    }

    /**
     * 묶음: 한 질문의 보기를 켜고 끈다. 같은 질문 안에서는 하나만 (다른 보기를 켜면 바뀜).
     * "해당 없음" 상태였으면 그것을 지우고 이 보기만.
     */
    fun toggleIn(p: Page.Bundle, field: String, value: Any?): QuestionSession {
        var base = picked
        if (bundleNone(p)) base = base - p.fields.toSet()
        val on = base.containsKey(field) && Question.sameValue(base[field], value)
        return if (on) copy(picked = base - field)
        else copy(picked = base + (field to value), cleared = cleared - field)
    }

    /** 묶음 "해당 없음": 켜면 질문마다 "해당 없음" 값, 다시 누르면 모두 끔 */
    fun toggleBundleNone(p: Page.Bundle): QuestionSession =
        if (bundleNone(p)) copy(picked = picked - p.fields.toSet())
        else copy(
            picked = picked + p.fields.associateWith { Bundles.NONE_VALUE[it] },
            cleared = cleared - p.fields.toSet(),
        )

    /**
     * "잘 모르겠어요"·"건너뛰기": 지금 화면에 답하지 않고 다음으로.
     * 한 질문·묶음은 답을 보내지 않고(전에 했던 답도 뺌), 여러 개 고르기는 빈 목록 [] (= 답 없음, 다시 묻지 않음)
     */
    fun skip(): QuestionSession = when (val p = page) {
        is Page.Multi -> copy(picked = picked + (p.q.field to emptyList<Any?>()), cleared = cleared - p.q.field)
        null -> this
        else -> copy(picked = picked - p.fields.toSet(), cleared = cleared + p.fields)
    }

    /** "잘 모르겠어요" (전 이름) */
    fun dontKnow(): QuestionSession = skip()

    /**
     * 다음 보일 화면으로. 끝이면 index가 pages.size (done).
     * 묶음에서 고르지 않은 질문은 답하지 않은 것으로 (추측하지 않음, 전에 했던 답도 뺌)
     */
    fun next(): QuestionSession {
        val p = page
        val left = if (p is Page.Bundle) p.fields.filterNot { picked.containsKey(it) } else emptyList()
        return copy(index = nextIndex(index) ?: pages.size, cleared = cleared + left)
    }

    fun prev(): QuestionSession = prevIndex(index)?.let { copy(index = it) } ?: this

    val done: Boolean get() = index >= pages.size

    /**
     * PUT할 답 전부: 지금까지의 답 + 이번 답 − 모르겠어요. 지금 조건에서 안 보이는 질문의 답도 그대로 둔다 (서버가 받음).
     * 단 과속 인과관계 답은 운전자 요인에서 과속을 뺐으면 뺀다 (과속 없이는 뜻이 없음)
     */
    fun answers(): Map<String, Any?> {
        val out = LinkedHashMap(base)
        cleared.forEach { out.remove(it) }
        out.putAll(picked)
        out.keys.filter { FollowUps.isAvoidable(it) && !FollowUps.speeding(out[FollowUps.factorsOf(it)]) }.forEach { out.remove(it) }
        return out
    }

    private fun nextIndex(from: Int): Int? = (from + 1 until pages.size).firstOrNull { visible(pages[it]) }
    private fun prevIndex(from: Int): Int? = (from - 1 downTo 0).firstOrNull { visible(pages[it]) }

    companion object {
        /**
         * 남은 질문에 답하기: remaining을 서버 순서 그대로 (상대 종류 질문이 맨 앞이면 그대로 맨 앞),
         * 그 뒤에 아직 답하지 않은 선택 질문 (운전자 요인·특수 상황, 여러 개 고르기)
         */
        fun remaining(case: BbCase): QuestionSession {
            val main = case.remaining.filter { it.answerable }
            val have = main.map { it.field }.toSet()
            val optional = case.optionalQuestions.filter { it.field !in have && it.field !in case.userAnswers }
            return QuestionSession(case.id, main + optional, case.userAnswers, case.values).start()
        }

        /**
         * 답을 보낸 뒤 새로 생긴 질문 (과속을 골랐을 때 "제한속도를 지켰다면 피할 수 있었나요?", 신호등 있음 → 신호 질문 등).
         * 이번 세션에서 보이지 않았던 remaining 질문만. 없으면 null (결과 화면으로)
         */
        fun followUp(case: BbCase, asked: Collection<String>): QuestionSession? {
            val qs = case.remaining.filter { it.answerable && it.field !in asked }
            if (qs.isEmpty()) return null
            val s = QuestionSession(case.id, qs, case.userAnswers, case.values, followUp = true).start()
            return if (s.done) null else s
        }

        /** "상대가 OO가 아니었나요?": 상대 종류 질문 하나. remaining에 있으면 그 질문(추정값 포함)을 쓴다 */
        fun otherCls(case: BbCase): QuestionSession? {
            val other = case.otherCls ?: return null
            val q = case.remaining.firstOrNull { it.field == BbCase.OtherCls.FIELD } ?: other.question()
            if (!q.answerable) return null
            return QuestionSession(case.id, listOf(q), case.userAnswers, case.values)
        }

        /**
         * 답변 고치기: 답한 질문(서버 answered, 선택 질문 포함 정의) + 남은 질문 + 답하지 않은 선택 질문, 지금 답으로 채워서.
         * 서버 응답만으로 만든다 (다른 기기에서 답한 질문도 고칠 수 있음).
         * 상대 종류에 답했는데 answered에 없으면(지금 장의 질문이 아님) 상대 종류 질문을 맨 앞에 둔다.
         */
        fun edit(case: BbCase): QuestionSession {
            val all = Questions.merge(Questions.merge(case.answered, case.remaining), case.optionalQuestions).toMutableList()
            val other = case.otherCls
            if (other != null && case.userAnswers.containsKey(BbCase.OtherCls.FIELD) &&
                all.none { it.field == BbCase.OtherCls.FIELD }
            ) all.add(0, other.question())
            val remainingFields = case.remaining.map { it.field }.toSet()
            val qs = Bundles.arrange(all.filter {
                it.answerable && (it.field in case.userAnswers || it.field in remainingFields || it.optional)
            })
            // 여러 개 고르기 답 []은 "고른 것 없음"이라 채우지 않는다 (다음이 꺼진 채 시작)
            val prefill = case.userAnswers.filter { (k, v) -> qs.any { it.field == k } && v != emptyList<Any?>() }
            return QuestionSession(case.id, qs, case.userAnswers, case.values, picked = prefill, editing = true).start()
        }
    }

    /** 처음 보일 화면으로 */
    fun start(): QuestionSession =
        if (pages.isEmpty() || visible(pages[0])) copy(index = 0) else copy(index = nextIndex(0) ?: pages.size)
}

object Questions {
    /** 질문 목록 합치기: 같은 키는 뒤 목록의 정의로 바꾸고, 처음 보는 것은 뒤에 붙인다 */
    fun merge(old: List<Question>, new: List<Question>): List<Question> {
        val byField = new.associateBy { it.field }
        val out = old.map { byField[it.field] ?: it }.toMutableList()
        val have = out.map { it.field }.toSet()
        new.filter { it.field !in have }.forEach { out.add(it) }
        return out
    }
}
