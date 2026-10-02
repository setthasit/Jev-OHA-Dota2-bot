local State = {}

local REGION_CELL_SIZE = 1000
local REGION_BY_SYMBOL = {
	T = 'top_lane',
	M = 'mid_lane',
	B = 'bot_lane',
	r = 'radiant_jungle',
	d = 'dire_jungle',
	['~'] = 'river',
	R = 'radiant_base',
	D = 'dire_base',
}
local REGION_ROWS_NORTH_TO_SOUTH = {
	'dddddddddddddDDDDDD',
	'dddddddddddddDDDDDD',
	'ddTTTTTTTTTTTDDDDDD',
	'ddTTTTTTTTTTTDDDDDD',
	'rrTTdddddddddDDDDDD',
	'rrTT~dddddddMMDDDDD',
	'rrTT~~~ddddMMMdBBdd',
	'rrTTrr~~ddMMMddBBdd',
	'rrTTrrr~~MMMdddBBdd',
	'rrTTrrrrMMMddddBBdd',
	'rrTTrrrMMM~~dddBBdd',
	'rrTTrrMMMrr~~ddBBdd',
	'rrTTrMMMrrrr~~~BBdd',
	'RRRRRMMrrrrrrr~BBdd',
	'RRRRRRrrrrrrrrrBBdd',
	'RRRRRRBBBBBBBBBBBrr',
	'RRRRRRBBBBBBBBBBBrr',
	'RRRRRRrrrrrrrrrrrrr',
	'RRRRRRrrrrrrrrrrrrr',
}
local REGION_GRID_RADIUS = ( #REGION_ROWS_NORTH_TO_SOUTH - 1 ) / 2

local ROSHAN_PIT_REGION = 'roshan_pit'
local ROSHAN_PIT_HALF_WIDTH = 600
local ROSHAN_PIT_CENTERS = {
	{ x = -2984, y = 2349 },
	{ x = 2980, y = -2816 },
}

local HP_BUCKETS = { edges = { 0.4, 0.7 }, names = { 'low', 'medium', 'high' } }
local PHASES = { edges = { 10 * 60, 30 * 60 }, names = { 'laning', 'mid', 'late' } }
local TOWER_THREAT_RADIUS = 1200

local deathByPlayer = {}

local function jmz()
	return require( GetScriptDirectory()..'/FunLib/jmz_func' )
end

local function towerIdsByLane()
	return {
		top = { t1 = TOWER_TOP_1, t2 = TOWER_TOP_2, t3 = TOWER_TOP_3 },
		mid = { t1 = TOWER_MID_1, t2 = TOWER_MID_2, t3 = TOWER_MID_3 },
		bot = { t1 = TOWER_BOT_1, t2 = TOWER_BOT_2, t3 = TOWER_BOT_3 },
	}
end

local function isRealNumber( value )
	return type( value ) == 'number' and value == value
end

local function isInRoshanPit( x, y )
	for _, center in ipairs( ROSHAN_PIT_CENTERS ) do
		if math.abs( x - center.x ) <= ROSHAN_PIT_HALF_WIDTH and math.abs( y - center.y ) <= ROSHAN_PIT_HALF_WIDTH then
			return true
		end
	end
	return false
end

local function gridOffset( coordinate )
	local offset = math.floor( coordinate / REGION_CELL_SIZE + 0.5 )
	return math.max( -REGION_GRID_RADIUS, math.min( REGION_GRID_RADIUS, offset ) )
end

function State.Region( x, y )
	if not ( isRealNumber( x ) and isRealNumber( y ) ) then return nil end
	if isInRoshanPit( x, y ) then return ROSHAN_PIT_REGION end
	local row = REGION_ROWS_NORTH_TO_SOUTH[REGION_GRID_RADIUS + 1 - gridOffset( y )]
	local column = REGION_GRID_RADIUS + 1 + gridOffset( x )
	return REGION_BY_SYMBOL[string.sub( row, column, column )]
end

function State.Bucket( value, edges, names )
	if not isRealNumber( value ) then return nil end
	for index, edge in ipairs( edges ) do
		if value < edge then return names[index] end
	end
	return names[#edges + 1]
end

local function regionOf( location )
	if location == nil then return nil end
	return State.Region( location.x, location.y )
end

local function hpBucket( unit )
	return State.Bucket( jmz().GetHP( unit ), HP_BUCKETS.edges, HP_BUCKETS.names )
end

local function clockText( seconds )
	local sign = seconds < 0 and '-' or ''
	local whole = math.floor( math.abs( seconds ) )
	return string.format( '%s%02d:%02d', sign, math.floor( whole / 60 ), whole % 60 )
end

local function wholeSeconds( seconds )
	if not isRealNumber( seconds ) or math.abs( seconds ) == math.huge then return nil end
	return math.floor( seconds )
end

local function deathSeenAt( playerId, now )
	local deathCount = GetHeroDeaths( playerId )
	local death = deathByPlayer[playerId]
	if death == nil or death.count ~= deathCount then
		death = { count = deathCount, seenAt = now }
		deathByPlayer[playerId] = death
	end
	return death.seenAt
end

local function secondsUntilRespawn( ally, playerId, isAlive, now )
	if isAlive then return 0 end
	-- GetRespawnTime() is the whole respawn duration, not the time left.
	local remaining = ally:GetRespawnTime() - ( now - deathSeenAt( playerId, now ) )
	return wholeSeconds( math.max( 0, remaining ) )
end

local function allyRecord( ally, now )
	local playerId = ally:GetPlayerID()
	local isAlive = IsHeroAlive( playerId )
	return {
		hero = GetSelectedHeroName( playerId ),
		position = jmz().GetPosition( ally ),
		region = regionOf( ally:GetLocation() ),
		hp = isAlive and hpBucket( ally ) or nil,
		level = ally:GetLevel(),
		alive = isAlive,
		respawn_seconds = secondsUntilRespawn( ally, playerId, isAlive, now ),
	}
end

local function allyRecords( team, now )
	local allies = {}
	for slot = 1, #GetTeamPlayers( team ) do
		local ally = GetTeamMember( slot )
		if ally ~= nil then allies[#allies + 1] = allyRecord( ally, now ) end
	end
	return allies
end

local function isVisibleRealHero( enemy )
	return enemy:CanBeSeen() and enemy:IsAlive() and not jmz().IsSuspiciousIllusion( enemy )
end

local function visibleEnemiesByPlayer()
	local enemyByPlayer = {}
	for _, enemy in ipairs( GetUnitList( UNIT_LIST_ENEMY_HEROES ) ) do
		if isVisibleRealHero( enemy ) then
			local playerId = enemy:GetPlayerID()
			enemyByPlayer[playerId] = enemyByPlayer[playerId] or enemy
		end
	end
	return enemyByPlayer
end

local function visibleEnemyRecord( playerId, enemy )
	return {
		hero = GetSelectedHeroName( playerId ),
		region = regionOf( enemy:GetLocation() ),
		hp = hpBucket( enemy ),
		level = enemy:GetLevel(),
	}
end

local function missingEnemyRecord( playerId )
	local record = { hero = GetSelectedHeroName( playerId ) }
	local info = GetHeroLastSeenInfo( playerId )
	local sighting = info ~= nil and info[1] or nil
	if sighting == nil then return record end
	local region = regionOf( sighting.location )
	local secondsSinceSeen = wholeSeconds( sighting.time_since_seen )
	if region ~= nil and secondsSinceSeen ~= nil then
		record.last_seen_region = region
		record.seconds_since_seen = secondsSinceSeen
	end
	return record
end

local function enemyRecords( enemyTeam, visibleEnemyByPlayer )
	local visible, missing, dead = {}, {}, {}
	for _, playerId in ipairs( GetTeamPlayers( enemyTeam ) ) do
		local enemy = visibleEnemyByPlayer[playerId]
		if not IsHeroAlive( playerId ) then
			dead[#dead + 1] = { hero = GetSelectedHeroName( playerId ) }
		elseif enemy ~= nil then
			visible[#visible + 1] = visibleEnemyRecord( playerId, enemy )
		else
			missing[#missing + 1] = missingEnemyRecord( playerId )
		end
	end
	return visible, missing, dead
end

local function countUnitsNear( unitByPlayer, center, radius )
	local count = 0
	for _, unit in pairs( unitByPlayer ) do
		local location = unit:GetLocation()
		local dx, dy = location.x - center.x, location.y - center.y
		if dx * dx + dy * dy <= radius * radius then count = count + 1 end
	end
	return count
end

local function towerRecord( tower, isAllied, visibleEnemyByPlayer )
	if tower == nil or not tower:IsAlive() then return { alive = false } end
	local record = {
		alive = true,
		enemy_heroes_near = countUnitsNear( visibleEnemyByPlayer, tower:GetLocation(), TOWER_THREAT_RADIUS ),
	}
	if isAllied or tower:CanBeSeen() then record.hp = hpBucket( tower ) end
	return record
end

local function towerRecords( team, visibleEnemyByPlayer )
	local isAllied = team == GetTeam()
	local recordsByLane = {}
	for lane, towerIdByTier in pairs( towerIdsByLane() ) do
		local recordByTier = {}
		for tier, towerId in pairs( towerIdByTier ) do
			recordByTier[tier] = towerRecord( GetTower( team, towerId ), isAllied, visibleEnemyByPlayer )
		end
		recordsByLane[lane] = recordByTier
	end
	return recordsByLane
end

function State.TeamMacro( team )
	if team ~= GetTeam() then return nil end
	local now = DotaTime()
	local enemyTeam = GetOpposingTeam()
	local visibleEnemyByPlayer = visibleEnemiesByPlayer()
	local enemiesVisible, enemiesMissing, enemiesDead = enemyRecords( enemyTeam, visibleEnemyByPlayer )
	return {
		time = clockText( now ),
		phase = State.Bucket( now, PHASES.edges, PHASES.names ),
		allies = allyRecords( team, now ),
		enemies_visible = enemiesVisible,
		enemies_missing = enemiesMissing,
		enemies_dead = enemiesDead,
		towers = {
			allied = towerRecords( team, visibleEnemyByPlayer ),
			enemy = towerRecords( enemyTeam, visibleEnemyByPlayer ),
		},
	}
end

return State
