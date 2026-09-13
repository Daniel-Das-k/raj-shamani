# Five new video-guide queries — 13 September 2026

Five fresh questions were frozen before this live run. Each was asked once using the current `video_guide` workflow, the configured `gpt-4.1-mini` model, and 50 ready videos. The application code and prompts were unchanged during the test. No indexing was performed.

## Result

**Two good responses with minor cleanup, one useful response needing revision, one failed response, and one appropriate no-match response.** This is an assistant assessment of the first responses against their cited captions, not an independent human benchmark or a general accuracy percentage. The test exercises retrieval and guide generation; it does not repeat browser playback tests or listen to the videos.

| Question | Result | Clips | Time |
| --- | --- | ---: | ---: |
| Why trust scam callers? | Good, with minor cleanup | 3 | 32.0s |
| Become CTO within six months? | Good, with minor cleanup | 3 | 30.7s |
| Get a small brand into Walmart? (Tamil) | Failed | 0 | 26.2s |
| What does Vaibhav automate, and how does he choose? | Useful, but needs revision | 2 | 29.1s |
| Exact sourdough recipe? | Appropriate no match | 0 | 9.2s |

All **8 returned citations** were reconstructed from the saved caption revision and matched the original quote, segment range, video title, timestamps and YouTube URL. This verifies provenance; it does not make every summary or relevance inference correct.

## Improvements indicated by this run

1. **Fix Tamil output consistency.** Correct evidence is being found, but English bridge descriptions cause a total rejection. The Walmart case demonstrates this clearly.
2. **Check each part of a question separately.** A clip covering tasks alone should not be treated as covering both tasks and the decision process. Preserve specific limitations per card.
3. **Prefer substantive clips over repeated opening montages.** The scam and AI results include introductions that repeat or compress fuller discussion.
4. **Keep relevance explanations tentative and attribution precise.** Explain why a clip may help without turning a guest’s discussion into universal career requirements or attributing an interviewer’s question to the guest.

The career and missing-recipe tests show the intended bridge behavior working: related material with honest limits, or no forced recommendation. Tamil reliability and multi-part coverage remain unresolved. No fixes were made as part of this check.

## Exact questions and returned responses

## 301. scam psychology

**Question:** Why do people trust scam callers even when there are warning signs?

**Returned status:** `recommendations` · **Coverage:** `direct`

**Returned message:** These video moments may help with your question. Each excerpt may cover only part of it.

### Moment 1: Why Fraud Calls Work: The Psychology of Trust & Authority | Sunil Bajpai | FO543 Raj Shamani

[Watch 00:08:53–00:10:19](https://www.youtube.com/watch?v=5pZuXAUke9w&t=533s) · Recorded match: `direct`

**Summary:** The video excerpt discusses how fraud calls exploit trust and authority, illustrating with an example of an elderly, respected man receiving a call from someone posing as a police officer. The scammer presents a problem but acts friendly and helpful, gradually building a complex story to gain the victim's trust, as explained by the speaker.

**Why it may help:** This summary directly explains how scammers exploit trust and authority by acting friendly and building complex stories, which helps understand why people trust scam callers despite warning signs.

**Limitation:** No specific limitation was returned.

<details>
<summary>Original cited captions</summary>

>> He's a Padma Bushian winner. >> Yes. >> Okay. >> Yes. He's a respectable man, intelligent man and a man who has seen life because he's uh 80 plus, >> right? So he's not a kid. >> Yeah. >> Not at all. >> Okay. So he gets a call from some random person appearing to be a police person. >> Yeah. some CBI officers and all that. >> Okay. >> And I and I want to point out that in all of these cases, the same elements would play out. >> What >> that there is somebody with authority who tells you that there is a problem. And the best part is you see in the compressed news stories that we get, we hear about coercion. We we hear about the arrest and and the drama. >> That's all real. But the scammer really is a friendly person. He tells you that there is a problem but he knows that uh you are not at fault. >> Okay? >> He will help you out. That's where the story begins. Otherwise you would not uh fall for it. No. Then he keeps building the story and and he keeps giving you more and more details and and like a movie >> that becomes complicated and the hero

</details>

### Moment 2: Why Fraud Calls Work: The Psychology of Trust & Authority | Sunil Bajpai | FO543 Raj Shamani

[Watch 00:48:58–00:50:25](https://www.youtube.com/watch?v=5pZuXAUke9w&t=2938s) · Recorded match: `related`

**Summary:** The video excerpt features a discussion on the psychological weaknesses scammers exploit, focusing on fear and greed, including emergency as a form of fear. The speaker mentions five tests to identify scams but notes none are foolproof, emphasizing the importance of recognizing when a conversation is initiated by someone else to avoid being drawn in by excitement or fear.

**Why it may help:** It discusses psychological weaknesses like fear and greed that scammers exploit, providing background on why people might fall for scams even when warning signs exist.

**Limitation:** It does not specifically explain why people trust scam callers, focusing more on identifying scams and psychological triggers.

<details>
<summary>Original cited captions</summary>

>> What weakness do they identify? Fear, greed, emergency, what is it? What what is best for scam? >> Fear and greed are good. Um emergency is a type of fear right. So fear and uh greed is what they usually work on. >> M >> and therefore you need to figure out where there is greed and where there is fear >> right and that they are very good very reliable markers to um to know that the scammer is is active. So you know at one stage you asked uh uh what could be done what how could these people act or or how do you identify >> on this so I give you five tests right I'm not offering any single solution anywhere >> because I want to prove to you that all of them will fail >> okay >> right so there have to be ways but what those ways are we'll arrive then >> first is the alarm something somebody initiated you did not. >> So first thing to to realize in a situation is that did you initiate this conversation? Somebody else initiated. >> If somebody else initiated and you seem to be getting sucked into it whether out of excitement or >> fear

</details>

### Moment 3: Why Fraud Calls Work: The Psychology of Trust & Authority | Sunil Bajpai | FO543 Raj Shamani

[Watch 00:00:00–00:01:01](https://www.youtube.com/watch?v=5pZuXAUke9w&t=0s) · Recorded match: `related`

**Summary:** The video excerpt discusses how scams work by using authority figures and friendly scammers to deceive victims, highlighting the large financial losses and the scale of the online scam industry. It also touches on the process of starting scams, including sourcing personal information and using various tools like voice cloning.

**Why it may help:** It highlights the use of authority figures and friendly scammers to deceive victims, giving context on scammer tactics that build trust.

**Limitation:** It focuses more on scam mechanics and industry scale rather than the victim's trust dynamics.

<details>
<summary>Original cited captions</summary>

So we've prepared this big board. [music] >> So explain me how the scam happened. >> In all of these cases, the same elements would play [music] out. >> What? >> That there is somebody with authority who tells you that there is a problem and the best part is the scammer is a friendly person. Otherwise you would not uh fall for it. No. >> So every year we lose 54,000 [music] cr to scams. We will have many more cuz about 10% people only ever report and this online scam industry is about $1.03 trillion perm. So this is about.9% of the world GDP. >> Explain me this industry first. [music] Who starts this? What are the steps involved? >> First is procurement. They source information about you. Your phone number. So there are on the dark web available. So that's a sourcing cost. Then manufacturing. There are uh toolkits available, websites available, >> voice cloning [music] tools available, >> whatever you want to do. But

</details>

**Assessment:** Good, with minor cleanup

**What worked:** The authority/friendly-helper example and fear/greed discussion are supported by the captions. The second card retains that no single scam test is foolproof and labels its narrower scope. The text is readable.

**What needs improvement:** The third recommendation is the opening montage and repeats the first card’s main mechanism. Prefer another substantive moment or show only the first two. The direct card could name Sunil Bajpai rather than repeatedly saying “the speaker.”

## 302. career / personal timeline

**Question:** I am a software engineer. How can I become a CTO within six months while staying at my current company?

**Returned status:** `recommendations` · **Coverage:** `related`

**Returned message:** I did not find a direct answer in the retrieved excerpts. These related moments may still be useful.

### Moment 1: Harvard MBA in 100 Minutes: Career Growth, Frameworks, Money & Skills | Ashwin | FO522 Raj Shamani

[Watch 01:20:59–01:22:14](https://www.youtube.com/watch?v=YVlWj1LCv54&t=4859s) · Recorded match: `related`

**Summary:** The speaker discusses the importance of strategically building a network beyond one's immediate circle to achieve the goal of becoming a CEO, emphasizing knowing key decision-makers like those in firms hiring CEOs and the board. They highlight the need to identify clear goals and focus efforts accordingly, rather than just moving fast without direction.

**Why it may help:** This summary highlights the importance of strategic networking and goal clarity, which are crucial steps toward advancing to executive roles like CTO within a company.

**Limitation:** It focuses on becoming a CEO and external networking rather than specific steps to become a CTO internally within six months.

<details>
<summary>Original cited captions</summary>

Reynolds or Egon Zehnder. How many people in those firms know me? My first to-do is I will get in the face of those firms that hire CEOs for bank. May be research karunga. Nam likhunga. And in the next 6 months they all must know me. >> Mhm. >> It's concrete. See, life is not is concrete. Once I know my goal, See, very often in India we're all very interested in running fast. I tell people first figure out which direction you want to run. Then run fast, otherwise you might be going further and further away from your goal. So, once you figure out that, that's just a simple example of >> What do I need to forget if I'm this person and I want to become CEO? >> Uh you may need to forget for example um >> Or challenge. >> No, so one is let's say today you have a if you are in this company in the mid-level, you will have a network that is probably within that small little function and you think that that is good enough. Build your network more broadly. In this company, who decides the CEO? Mhm. It'll be the board, maybe a CEO. There'll be How many of those people do I know? So, forget that my network in my little pond is sufficient. >> Uh just because I know five VPs and two CXOs in my bank is actually

</details>

### Moment 2: Top CTO's Advice: The Real Reason You Are Not Growing | Sauvik Banerjjee | FO558 Raj Shamani

[Watch 00:56:51–00:58:50](https://www.youtube.com/watch?v=XwawXRaNfzM&t=3411s) · Recorded match: `related`

**Summary:** The video excerpt discusses key traits that prevent someone from becoming a CEO, CTO, or CMO, highlighting issues like dishonesty, poor stakeholder management, and autocratic decision-making. It emphasizes the importance of accountability, collaboration, and supporting other teams in business roles.

**Why it may help:** It outlines key traits and behaviors to avoid and adopt, such as accountability and collaboration, which are essential for leadership roles like CTO.

**Limitation:** It discusses general traits preventing executive roles but does not provide a direct roadmap or timeline for becoming a CTO at the current company.

<details>
<summary>Original cited captions</summary>

the word officer means you have the responsibility and accountability of the business interest >> these five six do and what is a sign which instantly tells you that this person will never become a CEO or a CTO or a CMO or any officer. one we spoke about earlier blatantly floating with lies and non-deliverables >> basics give him chance after chance >> people do turn around second is he's not a good stakeholder manager stakeholder means if finance is having some problem and if I can go and sit in free finance workshops which has got nothing to do with me but I can give an way to solve a problem for him or hear him out because he was there supporting me last year when I was having budget issues. >> You're there for that team. Third thing is these are behavioral telemetry and signals. Third thing is he genuinely is an autocratic decision maker. Very autocratic decision maker. He's not involving people. He's taking decisions based on the chair he sits. >> So it's a bad bad person to have not a CXO sustainable CXO. You cannot be autocratic in a business. >> A business has a charter. Whether I'm building a phenomenal coffee um mug or uh building a excellent um cycle or building a great AI model, great AI company, how can I take autocratic decisions without involving

</details>

### Moment 3: Top CTO's Advice: The Real Reason You Are Not Growing | Sauvik Banerjjee | FO558 Raj Shamani

[Watch 00:20:43–00:22:18](https://www.youtube.com/watch?v=XwawXRaNfzM&t=1243s) · Recorded match: `related`

**Summary:** The video excerpt features a discussion about the importance of execution over perfection in growth, emphasizing learning through experience, experimentation, and continuous improvement rather than following a rigid, sequential 'waterfall' approach. The speakers highlight concepts like chaos engineering and agile methodologies as modern alternatives to traditional methods.

**Why it may help:** This summary emphasizes execution, learning, and agile methodologies, which are important for demonstrating leadership and technical excellence as a software engineer aspiring to be CTO.

**Limitation:** It focuses on execution and growth mindset rather than specific career advancement strategies or timelines for becoming CTO.

<details>
<summary>Original cited captions</summary>

>> So what happens is one is overthinking right thing to do. >> Money is involved. Right thing to do the other guy is pioneering learning and building it while you're doing it. Now that's my observation and I think that's the right way to do things because you never get it perfect right in the first go. This guy probably is wanting to get the perfection is a rubbish nonsense we are chasing. It's all execution. We are have to dependent. You're you're getting better with every podcast you're doing. I am getting better. My models are getting better with everything. August 2026 and 20 August 2025 there's a lot more learning the human mind is having. >> True. So I would rather experience, experiment, fail but keep on doing it rather than conceptualizing, architecting, you know, creating the concept and then taking a milestone. No, there's no waterfall world today, sequential waterfall world today. There is fundamentally a we have a concept in software engineering called chaos engineering. >> Okay, what is that? And chaos engineering is about figuring out how to go about it while going about it. >> Interesting. >> So technology waterfall everything is sequential requirements design build testing publish user group testing by like a flowchart >> like the flowchart. It's called a waterfall. Okay. >> Today then the world came as agile everything you have to be quick but

</details>

**Assessment:** Good, with minor cleanup

**What worked:** The response explicitly says no direct answer was found. All three cards are related matches with specific limits: CEO networking is not an internal six-month CTO plan, leadership traits are not a roadmap, and execution philosophy is not a career timeline. No promotion guarantee is invented.

**What needs improvement:** “Crucial steps” and “essential” in the relevance explanations are more prescriptive than necessary. “May help you explore…” would fit the guide role better. The final execution clip is a weaker match than the leadership clip.

## 303. Tamil / retail brand growth

**Question:** ஒரு சிறிய பிராண்டை Walmart போன்ற பெரிய கடைகளில் விற்பனைக்கு கொண்டு செல்ல என்ன செய்ய வேண்டும்?

**Returned status:** `invalid_evidence` · **Coverage:** `none`

**Returned message:** கிடைத்த பகுதிகளின் விளக்கங்களைச் சரிபார்க்க முடியவில்லை. மேலும் குறிப்பிட்ட கேள்வியுடன் தேடவும்.

**Assessment:** Failed

**What worked:** Retrieval found the correct Puneet Nanda episode, including licensing, private label and innovation passages. The error message is in Tamil and rejected drafts were withheld.

**What needs improvement:** The bridge generated English relevance explanations and limits even though the question and summaries were Tamil. Validation rejected the entire selection before source review. This is a generation/language failure, not missing video evidence. Some rejected Tamil summaries also need translation review; they were not displayed.

**Failure evidence:** `Recommendation is not in the requested language.` at `selection`. The selection contained English `why_relevant` text. None of those rejected drafts was shown to the user.

The retrieved [Puneet Nanda passage at 00:40:27–00:42:47](https://www.youtube.com/watch?v=czkPKQ9VIU8&t=2427s) explicitly discusses licensing, retailer private labels and innovation, so useful source content was present.

## 304. AI automation / named speaker

**Question:** Which repetitive tasks does Vaibhav Sisinty say he automates with AI, and how does he decide what to automate?

**Returned status:** `recommendations` · **Coverage:** `direct`

**Returned message:** These video moments may help with your question. Each excerpt may cover only part of it.

### Moment 1: How AI Makes Him Crores: Second Brain, Automations & Systems | Vaibhav Sisinty | FO557 Raj Shamani

[Watch 00:00:59–00:02:07](https://www.youtube.com/watch?v=LqY6hFLMEJw&t=59s) · Recorded match: `direct`

**Summary:** Vaibhav Sisinty explains how he uses AI to organize and extract value from his daily YouTube content by creating JSON cards from transcripts, monitors Slack conversations with a triage system, and transcribes team standup meetings into a GitHub repository for easy access. He also hints at developing an agent to automate these processes.

**Why it may help:** Vaibhav Sisinty details specific repetitive tasks he automates with AI, such as creating JSON cards from YouTube transcripts, monitoring Slack with a triage system, and transcribing meetings into GitHub, illustrating his practical automation use.

**Limitation:** No specific limitation was returned.

<details>
<summary>Original cited captions</summary>

Let's say YouTube content that I'm watching every day is very very valuable. How do I feed the same context to AI? So I built a daily rapper which opens my YouTube history, goes through all the videos, ranks all the pieces of content, everything that I've seen of AI, it pulls that data, converts the transcripts and looks at what are the key pointers, saves it in form of JSON cards. JSON cards, what is the value pack of each one of the podcast is what it saves. That is one. Two is a lot of times when I watch content on AI, I share it with my team. Where do I share it? I share it on my Slack. So, I have a triage running for my Slack which looks at what are the conversations I'm having. This is number two. Three, I realized one of the highest value conversations that I have today is inside of standups with my team. Every single meeting is transcribed, [music] put in a GitHub repository and inside of the repository, my team can access that information at any point of time. Finally, oh my god, how can I forget this? This is a game changer which is >> what is the easiest way to make an agent who do all of this? >> There is something [music] >> I have a small favor to ask you. I need

</details>

### Moment 2: How AI Makes Him Crores: Second Brain, Automations & Systems | Vaibhav Sisinty | FO557 Raj Shamani

[Watch 00:38:09–00:39:23](https://www.youtube.com/watch?v=LqY6hFLMEJw&t=2289s) · Recorded match: `related`

**Summary:** Vaibhav Sisinty discusses the importance of reimagining processes with AI capabilities rather than simply automating existing human tasks, using content creation as an example where topic selection and packaging are key steps.

**Why it may help:** This passage explains Vaibhav's approach to deciding what to automate, emphasizing reimagining processes with AI rather than just automating existing tasks, which informs his decision-making framework.

**Limitation:** It does not list specific repetitive tasks he automates, focusing instead on his philosophy of automation.

<details>
<summary>Original cited captions</summary>

>> The answer for winning is a process of how we think with AI >> where every time I try to set up a process across company. Here we are going to talk about content example right now across the company. The biggest mistake people do is they will see what is a human doing right now where all I can plug AI so that it can be done better. That's a fundamentally wrong process. >> Okay, >> you have to reimagine that whole process with capabilities of AI in the mind. That is when you build a great process. For example, for content, what is the first step for someone like us who create education content? One is topic selection. >> M >> okay. >> This plays a very important role. >> This is game >> game. No, topic selection is one. I'll tell you what game is. Game is this packaging. >> What we select as a topic here? The topic is we'll talk about AI. Okay. I mean you know packaging really well but you get what I'm saying. >> Yeah. >> Second is >> for me topic is packaging. >> Okay. For me topic is topic. What am I choosing?

</details>

**Assessment:** Useful, but needs revision

**What worked:** Both cards come from the correct Vaibhav Sisinty episode. The first locates actual YouTube-history/transcript cards, Slack monitoring and meeting transcripts. The second locates his view that processes should be reimagined around AI capabilities, complementing the first.

**What needs improvement:** The first card is classified direct with no specific limitation although it mainly answers the tasks half of a two-part question. “His daily YouTube content” should clearly say content he watches. “He also hints at developing an agent” is imprecise attribution: the cited ending includes a question about making an agent. Keep the summary to clearly stated activities. The first clip is an introductory montage; prefer its full discussion if available.

## 305. missing content

**Question:** Give me a step-by-step sourdough bread recipe with exact ingredient weights and baking temperatures.

**Returned status:** `insufficient_evidence` · **Coverage:** `none`

**Returned message:** I could not find a useful match in the retrieved video excerpts.

**Assessment:** Appropriate no match

**What worked:** Returns no useful match and no recipe, ingredients, temperatures or unrelated food-business recommendations. The claim is correctly scoped to retrieved excerpts.

**What needs improvement:** This result does not prove the entire channel has no recipe; retrieval is bounded. The current wording avoids that broader claim.

## Saved artifacts

- Frozen questions and review criteria: [guide_five_query_check_20260913.json](tests/fixtures/guide_five_query_check_20260913.json).
- Full local responses, retrieval results, original captions, source readings, bridge selections, verifier decisions, timings, token counts and code hashes: `data/accuracy-review/video-guide-five-query-check-20260913.json`.
- Local assessment and citation checks: `data/accuracy-review/video-guide-five-query-assessment-20260913.json`.
- Raw artifacts remain in the ignored data directory. This report reproduces all five returned messages and all eight displayed cards. Rejected drafts are retained only in the raw diagnostic file.
- No Git push was performed.
