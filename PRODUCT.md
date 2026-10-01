<!-- impeccable:product-schema 1 -->
# TurkiSib

Web demo of an advisory railway ML/LLM service for a four-person hackathon team. Primary users are presenters, judges and dispatchers exploring a synthetic rail scenario.

The first surface combines a train dispatch screen, an interactive model laboratory and chat. Users select a train, change its conditions, inspect a real model prediction and ask about that same scenario. No live train control is performed.

The user chose a working screen immediately and delegated the stack. Serve plain HTML/CSS/JavaScript from the existing Python FastAPI service, without a Node build requirement. Interface language: Russian. Support desktop and mobile, keyboard use and reduced motion.

The trained LightGBM models predict next-segment delay change and a calibrated proxy risk, not a validated conflict within 15 minutes. Passenger models were trained on PKP data; unsupported train types use a visibly labelled rule fallback. All dispatcher positions are demonstration inputs. Solver outputs must not be invented. API credentials remain server-side.

Primary success: the user can change a train's delay, see measured prediction changes, understand limitations, and obtain chat answers grounded in the edited snapshot. A future landing page must preserve these factual boundaries.
