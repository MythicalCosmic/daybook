# Development isolation per work package (docs/PLAN-OWNER.md §2.4): each package gets its own
# database, Redis database and ports, so several people (or agents) can run the stack at once.
#
#   make run PKG=e            # Django for package E on :28150, database trello_e, Redis DB 5
#   make pkg-db PKG=e         # create trello_e and migrate it
#   eval "$(make -s pkg-env PKG=e)"   # the same settings in your shell
#
# Without PKG nothing is overridden and .env decides (the lead's everyday setup).
#
# Columns: package : database : Redis DB : backend : dashboard : mini app : stream.
# Package n (A=1 … R=15, then S, T, Q, U) has backend port 28100 + 10n and the next three ports
# for the dashboard, the mini app and the stream; test databases are test_trello_<package>.
# W0-F works as D. G's stream is 28175 because 28173 is the lead's mini app.
# Redis needs more than its default 16 databases for S, T, Q and U (docker-compose.yml starts it
# with 32).
DEV_PACKAGES := \
	lead:trello:0:28000:28174:28173:28001 \
	a:trello_a:1:28110:28111:28112:28113 \
	b:trello_b:2:28120:28121:28122:28123 \
	c:trello_c:3:28130:28131:28132:28133 \
	d:trello_d:4:28140:28141:28142:28143 \
	e:trello_e:5:28150:28151:28152:28153 \
	f:trello_f:6:28160:28161:28162:28163 \
	g:trello_g:7:28170:28171:28172:28175 \
	h:trello_h:8:28180:28181:28182:28183 \
	i:trello_i:9:28190:28191:28192:28193 \
	j:trello_j:10:28200:28201:28202:28203 \
	k:trello_k:11:28210:28211:28212:28213 \
	l:trello_l:12:28220:28221:28222:28223 \
	n:trello_n:13:28230:28231:28232:28233 \
	p:trello_p:14:28240:28241:28242:28243 \
	r:trello_r:15:28250:28251:28252:28253 \
	s:trello_s:16:28260:28261:28262:28263 \
	t:trello_t:17:28270:28271:28272:28273 \
	q:trello_q:18:28280:28281:28282:28283 \
	u:trello_u:19:28290:28291:28292:28293

# Where the docker-compose.yml database and Redis listen on this machine.
DEV_DB_URL ?= postgres://trello:trello@localhost:25432
DEV_REDIS_URL ?= redis://localhost:26379

ifdef PKG
PKG_ROW := $(filter $(PKG):%,$(DEV_PACKAGES))
ifeq ($(PKG_ROW),)
$(error Unknown PKG=$(PKG). Known: $(foreach row,$(DEV_PACKAGES),$(firstword $(subst :, ,$(row)))))
endif
PKG_FIELDS := $(subst :, ,$(PKG_ROW))
PKG_DB := $(word 2,$(PKG_FIELDS))
PKG_REDIS_DB := $(word 3,$(PKG_FIELDS))
BACKEND_PORT := $(word 4,$(PKG_FIELDS))
DASHBOARD_PORT := $(word 5,$(PKG_FIELDS))
MINIAPP_PORT := $(word 6,$(PKG_FIELDS))
STREAM_PORT := $(word 7,$(PKG_FIELDS))
# The lead's tests use test_trello, everyone else's test_trello_<package>.
PKG_PYTEST_DB := $(if $(filter lead,$(PKG)),,$(PKG))
# Cache, broker and bot conversations share the package's Redis database; REDIS_KEY_PREFIX keeps
# the keys apps.core.redis writes apart as well.
PKG_ENV := \
	DATABASE_URL=$(DEV_DB_URL)/$(PKG_DB) \
	REDIS_URL=$(DEV_REDIS_URL)/$(PKG_REDIS_DB) \
	CELERY_BROKER_URL=$(DEV_REDIS_URL)/$(PKG_REDIS_DB) \
	BOT_FSM_REDIS_URL=$(DEV_REDIS_URL)/$(PKG_REDIS_DB) \
	REDIS_KEY_PREFIX=$(PKG): \
	PYTEST_DB=$(PKG_PYTEST_DB)
else
PKG_DB :=
BACKEND_PORT := 28000
DASHBOARD_PORT := 28174
MINIAPP_PORT := 28173
STREAM_PORT := 28001
PKG_ENV :=
endif

# What the Vite dev servers read: their own port, and where Django and the stream service are.
VITE_ENV = API_PORT=$(BACKEND_PORT) BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) \
	STREAM_PORT=$(STREAM_PORT) STREAM_URL=http://127.0.0.1:$(STREAM_PORT)
