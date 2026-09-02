"""Play-by-play battle commentary generator using LLMs."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from rotomarena.llm.client import LLMClient
from rotomarena.telemetry.replay_saver import _flatten_logs


class TurnCommentary(BaseModel):
    """Commentary script for a single battle turn."""

    turn: int
    title: str = ""
    commentary: str


class BattleCommentary(BaseModel):
    """Full match play-by-play commentary script."""

    match_id: str
    format: str = "gen9ou"
    p1_name: str
    p2_name: str
    winner: Optional[str] = None
    total_turns: int = 0
    language: str = "en-US"
    turns: List[TurnCommentary] = Field(default_factory=list)

    def get_turn(self, turn_num: int) -> Optional[TurnCommentary]:
        """Retrieve commentary for a specific turn number."""
        for t in self.turns:
            if t.turn == turn_num:
                return t
        return None


def get_commentary_system_prompt(language: str = "en-US") -> str:
    """Constructs the system prompt with explicit language requirements."""
    lang_clean = language.lower().strip()
    if "pt" in lang_clean or "br" in lang_clean:
        lang_instruction = (
            "LANGUAGE REQUIREMENT: Generate ALL commentary and titles in natural Brazilian Portuguese (Português do Brasil - pt-BR). "
            "Use standard competitive Pokémon terminology used in Brazilian esports broadcasts (e.g. 'Pedras Furtivas / Stealth Rock', 'troca', 'nocaute', 'dano massivo', 'Teracristalização', 'fim de jogo'). "
            "Write in natural conversational spoken Portuguese suitable for Text-To-Speech (TTS) narration."
        )
    elif "es" in lang_clean:
        lang_instruction = (
            "LANGUAGE REQUIREMENT: Generate ALL commentary and titles in Spanish (Español). "
            "Write in natural conversational spoken Spanish suitable for Text-To-Speech (TTS) narration."
        )
    elif "ja" in lang_clean:
        lang_instruction = (
            "LANGUAGE REQUIREMENT: Generate ALL commentary and titles in Japanese (日本語). "
            "Write in natural conversational spoken Japanese suitable for Text-To-Speech (TTS) narration."
        )
    elif "fr" in lang_clean:
        lang_instruction = (
            "LANGUAGE REQUIREMENT: Generate ALL commentary and titles in French (Français). "
            "Write in natural conversational spoken French suitable for Text-To-Speech (TTS) narration."
        )
    elif "de" in lang_clean:
        lang_instruction = (
            "LANGUAGE REQUIREMENT: Generate ALL commentary and titles in German (Deutsch). "
            "Write in natural conversational spoken German suitable for Text-To-Speech (TTS) narration."
        )
    else:
        lang_instruction = (
            "LANGUAGE REQUIREMENT: Generate ALL commentary and titles in natural conversational spoken English suitable for Text-To-Speech (TTS) narration."
        )

    return f"""You are a world-class competitive Pokémon esports color commentator (in the style of official Smogon Champions League and Pokémon VGC World Championships).
Your job is to provide engaging, high-energy, and strategically insightful play-by-play commentary for each turn of a Pokémon battle.

Tone & Style Guidelines:
1. Energetic & Professional: Treat this like an elite championship esports broadcast.
2. {lang_instruction}
3. Punchy & Spoken-Friendly: Avoid markdown asterisks, emojis, or bullet points in the commentary text.
4. Length: Keep each turn's commentary between 25 to 45 words so turn narration remains brisk and well-paced.
5. Insights: Highlight tactical momentum, critical reads, type matchups, damage thresholds, hazards, and sacrifices.
6. Structure: Provide an intro for Turn 0 (previewing matchup & leads), commentary for every combat turn, and a victory outro on the final turn.

Return ONLY a valid JSON object with the following schema:
{{
  "turns": [
    {{
      "turn": 0,
      "title": "Opening Leads",
      "commentary": "..."
    }},
    {{
      "turn": 1,
      "title": "Turn 1",
      "commentary": "..."
    }}
  ]
}}
"""


COMMENTARY_SYSTEM_PROMPT = get_commentary_system_prompt("en-US")


class CommentaryGenerator:
    """Generates structured play-by-play narration from battle logs and AI telemetry."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def parse_turn_events(
        self,
        raw_logs: Any,
        breadcrumbs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[int, List[str]]:
        """Group and summarize battle protocol lines and AI decisions by turn number."""
        lines = _flatten_logs(raw_logs)
        turn_events: Dict[int, List[str]] = {0: []}
        current_turn = 0

        for line in lines:
            if line.startswith("|turn|"):
                parts = line.split("|")
                if len(parts) >= 3 and parts[2].isdigit():
                    current_turn = int(parts[2])
                    if current_turn not in turn_events:
                        turn_events[current_turn] = []
            elif line.startswith("|switch|") or line.startswith("|drag|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    player = "Player 1" if "p1" in parts[2] else "Player 2"
                    mon = parts[3].split(",")[0]
                    hp = parts[4] if len(parts) >= 5 else ""
                    turn_events[current_turn].append(f"{player} sent out {mon} ({hp})")
            elif line.startswith("|move|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    user = parts[2]
                    move = parts[3]
                    target = parts[4] if len(parts) >= 5 else ""
                    target_str = f" targeting {target}" if target else ""
                    turn_events[current_turn].append(f"{user} used {move}{target_str}")
            elif line.startswith("|-damage|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    mon = parts[2]
                    hp = parts[3]
                    turn_events[current_turn].append(f"{mon} took damage: {hp}")
            elif line.startswith("|-heal|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    mon = parts[2]
                    hp = parts[3]
                    turn_events[current_turn].append(f"{mon} restored HP to {hp}")
            elif line.startswith("|faint|"):
                parts = line.split("|")
                if len(parts) >= 3:
                    turn_events[current_turn].append(f"{parts[2]} FAINTED!")
            elif line.startswith("|-terastallize|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    turn_events[current_turn].append(f"{parts[2]} Terastallized into {parts[3]}!")
            elif line.startswith("|-weather|"):
                parts = line.split("|")
                if len(parts) >= 3:
                    turn_events[current_turn].append(f"Weather: {parts[2]}")
            elif line.startswith("|-sidestart|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    turn_events[current_turn].append(f"Hazard set on {parts[2]}: {parts[3]}")
            elif line.startswith("|win|"):
                parts = line.split("|")
                if len(parts) >= 3:
                    turn_events[current_turn].append(f"MATCH FINISHED: {parts[2]} WINS!")

        # Inject AI thoughts from breadcrumbs if available
        if breadcrumbs:
            for b in breadcrumbs:
                t_num = b.get("turn", 0)
                reasoning = b.get("reasoning", "")
                agent_name = b.get("agent_name", "AI")
                if t_num in turn_events and reasoning:
                    # Clean thoughts for prompt
                    short_reasoning = reasoning.replace("\n", " ").strip()
                    if len(short_reasoning) > 120:
                        short_reasoning = short_reasoning[:120] + "..."
                    turn_events[t_num].append(f"[{agent_name} tactical intent: {short_reasoning}]")

        return turn_events

    def build_commentary_prompt(
        self,
        turn_events: Dict[int, List[str]],
        p1_name: str,
        p2_name: str,
        winner: Optional[str] = None,
        format_str: str = "gen9ou",
    ) -> str:
        """Format turn events into a clear prompt for LLM commentary generation."""
        lines = [
            f"Battle Overview:",
            f"- Format: {format_str}",
            f"- Player 1 (p1): {p1_name}",
            f"- Player 2 (p2): {p2_name}",
            f"- Winner: {winner or 'Draw/Undecided'}",
            f"- Total Turns: {max(turn_events.keys()) if turn_events else 0}",
            "",
            "Turn-by-Turn Events Log:",
        ]

        for t_num in sorted(turn_events.keys()):
            events = turn_events[t_num]
            if t_num == 0:
                header = "Turn 0 (Match Introduction & Team Preview / Opening Leads):"
            else:
                header = f"Turn {t_num}:"
            lines.append(header)
            if events:
                for ev in events:
                    lines.append(f"  - {ev}")
            else:
                lines.append("  - Turn resolved.")
            lines.append("")

        lines.append("Now generate engaging, hype, spoken-friendly esports commentary for each turn (Turn 0 through end) as JSON.")
        return "\n".join(lines)

    async def generate_commentary(
        self,
        raw_logs: Any,
        p1_name: str,
        p2_name: str,
        match_id: str,
        winner: Optional[str] = None,
        total_turns: int = 0,
        format_str: str = "gen9ou",
        language: str = "en-US",
        breadcrumbs: Optional[List[Dict[str, Any]]] = None,
    ) -> BattleCommentary:
        """Generate structured battle commentary for the entire match."""
        turn_events = self.parse_turn_events(raw_logs, breadcrumbs=breadcrumbs)
        max_turn = max(turn_events.keys()) if turn_events else total_turns
        total_turns = max(total_turns, max_turn)

        user_prompt = self.build_commentary_prompt(
            turn_events=turn_events,
            p1_name=p1_name,
            p2_name=p2_name,
            winner=winner,
            format_str=format_str,
        )

        sys_prompt = get_commentary_system_prompt(language)
        is_pt = "pt" in language.lower() or "br" in language.lower()

        try:
            response = await self.llm_client.generate_text(
                prompt=user_prompt,
                system_prompt=sys_prompt,
            )

            # Parse JSON from response
            cleaned_resp = response.strip()
            if "```json" in cleaned_resp:
                cleaned_resp = cleaned_resp.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned_resp:
                cleaned_resp = cleaned_resp.split("```")[1].split("```")[0].strip()

            parsed_data = json.loads(cleaned_resp)
            turns_data = parsed_data.get("turns", [])

            turn_commentaries = []
            for item in turns_data:
                turn_commentaries.append(
                    TurnCommentary(
                        turn=int(item.get("turn", 0)),
                        title=str(item.get("title", f"Turn {item.get('turn', 0)}")),
                        commentary=str(item.get("commentary", "")).strip(),
                    )
                )

            # Ensure all turns exist
            existing_turns = {tc.turn for tc in turn_commentaries}
            for t in range(total_turns + 1):
                if t not in existing_turns:
                    if t == 0:
                        title = "Introdução da Partida" if is_pt else "Match Intro"
                        text = f"Bem-vindos ao RotomArena! {p1_name} enfrenta {p2_name} neste confronto de Gen 9 OU!" if is_pt else f"Welcome to the arena! {p1_name} faces off against {p2_name} in this Gen 9 OU clash!"
                    elif t == total_turns and winner:
                        title = f"Turno {t} - Vitória" if is_pt else f"Turn {t} - Victory"
                        text = f"Fim de jogo! {winner} garante a vitória após uma batalha eletrizante de {total_turns} turnos!" if is_pt else f"That seals it! {winner} claims victory after an intense {total_turns}-turn battle!"
                    else:
                        title = f"Turno {t}" if is_pt else f"Turn {t}"
                        text = f"A ação continua no Turno {t} com ambos os treinadores disputando a vantagem." if is_pt else f"Action continues in Turn {t} as both trainers jockey for position."
                    turn_commentaries.append(TurnCommentary(turn=t, title=title, commentary=text))

            turn_commentaries.sort(key=lambda x: x.turn)

            return BattleCommentary(
                match_id=match_id,
                format=format_str,
                p1_name=p1_name,
                p2_name=p2_name,
                winner=winner,
                total_turns=total_turns,
                language=language,
                turns=turn_commentaries,
            )

        except Exception as e:
            # Safe heuristic fallback commentary if LLM call fails
            fallback_turns = []
            for t in range(total_turns + 1):
                if t == 0:
                    text = f"Bem-vindos ao RotomArena! {p1_name} batalha contra {p2_name} em Gen 9 OU." if is_pt else f"Welcome to RotomArena! {p1_name} battles {p2_name} in Gen 9 OU."
                    title = "Abertura" if is_pt else "Opening Setup"
                elif t == total_turns and winner:
                    text = f"E {winner} garante a vitória no Turno {t}!" if is_pt else f"And {winner} takes the victory in Turn {t}!"
                    title = "Conclusão" if is_pt else "Match Conclusion"
                else:
                    events = turn_events.get(t, [])
                    summary_events = ", ".join(events[:2]) if events else ("Os jogadores fazem suas jogadas táticas." if is_pt else "Both players make their tactical choices.")
                    text = f"Turno {t}: {summary_events}" if is_pt else f"Turn {t}: {summary_events}"
                    title = f"Turno {t}" if is_pt else f"Turn {t}"
                fallback_turns.append(TurnCommentary(turn=t, title=title, commentary=text))

            return BattleCommentary(
                match_id=match_id,
                format=format_str,
                p1_name=p1_name,
                p2_name=p2_name,
                winner=winner,
                total_turns=total_turns,
                language=language,
                turns=fallback_turns,
            )
