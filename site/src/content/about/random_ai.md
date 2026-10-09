---
title: Chimps at the Zoo, and why they are here
---

<div class="credit">

**Named for Hans Rosling's chimpanzees.** In
[How not to be ignorant about the world](https://www.youtube.com/watch?v=Sm5xF-UYgdg) (TED, with Ola Rosling),
he compares people's answers to a quiz about the world with chimpanzees in a zoo picking answers at random, and
the chimps keep winning. Here, the question is whether a model plays Pokémon better than they would.

</div>

Every turn, the chimps pick one of their legal actions at random: any move, any switch, Terastallization included,
with no regard for what is on the other side of the field. They lead with a random Pokémon. They have no
evaluation, no memory and no opinions. (In the code and the old records they are `random_ai`.)

## Why they are in the rankings

**They are the floor.** A model that cannot reliably beat an opponent choosing at random is not playing Pokémon in
any useful sense, and usually turns out to be failing to answer at all.

**They borrow your team.** When models play the teams they built themselves, the chimps can't build one, so they
play their opponent's: both sides bring the identical six. The only difference left is who chooses the moves, a
model or a chimp. Losing to them means playing worse than random with your own team.

**They keep the scale honest.** A rating means little until you know what a random policy scores on the same
scale. The chimps are rated from their games like everyone else, with error bars, and appear on the leaderboard
without a rank number, as a reference line rather than a contestant.

**They win sometimes.** Pokémon has damage rolls, critical hits, accuracy checks and speed ties, and a random
policy occasionally clicks the right button at the right moment. Every win they record is published, along with
the reasoning of the model they beat.
